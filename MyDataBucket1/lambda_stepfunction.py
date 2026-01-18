import os
import json
import boto3
import pymysql
import csv
from io import StringIO
from datetime import datetime
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_rds_credentials(secret_arn, region=None):
    """Get RDS credentials from Secrets Manager with version info"""
    secrets_client = boto3.client('secretsmanager', region_name=region) if region else boto3.client('secretsmanager')
    
    try:
        # Get the secret value
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        
        if 'SecretString' in response:
            secret = json.loads(response['SecretString'])
        else:
            # For binary secrets
            secret = json.loads(response['SecretBinary'].decode('utf-8'))
        
        logger.info(f"Retrieved secret version: {response.get('VersionId', 'N/A')}")
        logger.info(f"Secret ARN: {response.get('ARN', 'N/A')}")
        
        return {
            'username': secret.get('username'),
            'password': secret.get('password'),
            'host': secret.get('host'),  # Might be in secret
            'database': secret.get('dbname', 'MyDatabase'),
            'port': secret.get('port', '3306'),
            'engine': secret.get('engine', 'mysql')
        }
        
    except Exception as e:
        logger.error(f"Error retrieving secret {secret_arn}: {str(e)}")
        raise

def get_rds_endpoint(rds_instance_id, region):
    """Get RDS endpoint from RDS API"""
    try:
        rds_client = boto3.client('rds', region_name=region)
        response = rds_client.describe_db_instances(
            DBInstanceIdentifier=rds_instance_id
        )
        
        if not response['DBInstances']:
            raise ValueError(f"RDS instance {rds_instance_id} not found")
        
        instance = response['DBInstances'][0]
        endpoint = instance['Endpoint']['Address']
        logger.info(f"Retrieved RDS endpoint: {endpoint} (Status: {instance.get('DBInstanceStatus', 'Unknown')})")
        
        return endpoint
        
    except Exception as e:
        logger.error(f"Error getting RDS endpoint for {rds_instance_id}: {str(e)}")
        raise

def create_table_if_not_exists(cursor, table_name, columns):
    """Create table with dynamic columns based on CSV header"""
    # Basic columns for metadata
    column_definitions = []
    for col in columns:
        # Clean column name for SQL
        clean_col = col.replace('"', '').replace("'", "").replace('`', '')
        column_definitions.append(f'`{clean_col}` TEXT')
    
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
        id INT AUTO_INCREMENT PRIMARY KEY,
        file_name VARCHAR(255),
        s3_bucket VARCHAR(255),
        s3_key VARCHAR(500),
        upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        processed BOOLEAN DEFAULT FALSE,
        rows_count INT DEFAULT 0,
        error_message TEXT,
        {', '.join(column_definitions)},
        INDEX idx_upload_time (upload_timestamp),
        INDEX idx_file_name (file_name),
        INDEX idx_processed (processed),
        INDEX idx_s3_bucket_key (s3_bucket, s3_key(100))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ROW_FORMAT=DYNAMIC
    """
    
    cursor.execute(create_table_sql)
    logger.info(f"Table {table_name} created or already exists")
    return column_definitions

def insert_csv_data(cursor, table_name, columns, csv_reader, bucket_name, object_key):
    """Insert CSV data into RDS table"""
    # Clean column names for SQL
    clean_columns = [col.replace('"', '').replace("'", "").replace('`', '') for col in columns]
    columns_str = ', '.join([f'`{col}`' for col in clean_columns])
    placeholders = ', '.join(['%s'] * len(clean_columns))
    
    # Insert SQL with file metadata
    insert_sql = f"""
    INSERT INTO `{table_name}` 
    (file_name, s3_bucket, s3_key, {columns_str}) 
    VALUES (%s, %s, %s, {placeholders})
    """
    
    row_count = 0
    file_name = object_key.split('/')[-1]
    batch_size = 100  # Commit every 100 rows
    
    for row in csv_reader:
        # Validate row has same number of columns as header
        if len(row) != len(clean_columns):
            logger.warning(f"Row {row_count+1} has {len(row)} columns, expected {len(clean_columns)}. Skipping.")
            continue
        
        # Clean row data (remove quotes, trim whitespace)
        clean_row = [cell.strip().replace('"', '').replace("'", "") for cell in row]
        
        # Add file metadata to row data
        full_row = [file_name, bucket_name, object_key] + clean_row
        
        try:
            cursor.execute(insert_sql, full_row)
            row_count += 1
        except pymysql.Error as e:
            logger.error(f"Error inserting row {row_count+1}: {str(e)}")
            # Skip problematic row and continue
            continue
        
        # Batch commit
        if row_count % batch_size == 0:
            cursor.connection.commit()
            logger.info(f"Committed {row_count} rows...")
    
    # Final commit
    cursor.connection.commit()
    logger.info(f"Total rows inserted: {row_count}")
    return row_count

def trigger_step_functions(state_machine_arn, input_data, execution_name, region=None):
    """Trigger Step Functions workflow"""
    try:
        stepfunctions_client = boto3.client('stepfunctions', region_name=region) if region else boto3.client('stepfunctions')
        
        # Validate input data size (Step Functions has 256KB limit)
        input_json = json.dumps(input_data)
        if len(input_json) > 250 * 1024:  # Leave some buffer
            logger.warning(f"Input data size ({len(input_json)} bytes) approaching Step Functions limit")
            # Truncate large data
            input_data['large_data_warning'] = True
            input_data['original_size'] = len(input_json)
            input_json = json.dumps(input_data)
        
        response = stepfunctions_client.start_execution(
            stateMachineArn=state_machine_arn,
            input=input_json,
            name=execution_name[:80]  # Step Functions limit: 80 chars
        )
        
        logger.info(f"Started Step Functions execution: {response['executionArn']}")
        return response['executionArn']
        
    except Exception as e:
        logger.error(f"Error triggering Step Functions: {str(e)}")
        raise

def update_processing_status(cursor, table_name, file_name, rows_count, error_message=None):
    """Update processing status in the database"""
    try:
        if error_message:
            # Truncate error message if too long
            if len(error_message) > 1000:
                error_message = error_message[:997] + "..."
            
            update_sql = f"""
            UPDATE `{table_name}` 
            SET rows_count = %s, processed = TRUE, error_message = %s 
            WHERE file_name = %s
            """
            cursor.execute(update_sql, (rows_count, error_message, file_name))
        else:
            update_sql = f"""
            UPDATE `{table_name}` 
            SET rows_count = %s, processed = TRUE 
            WHERE file_name = %s
            """
            cursor.execute(update_sql, (rows_count, file_name))
        
        cursor.connection.commit()
        logger.info(f"Updated processing status for {file_name}: {rows_count} rows")
        
    except Exception as e:
        logger.error(f"Error updating processing status: {str(e)}")
        # Don't raise, continue processing

def process_csv_file(s3_client, bucket_name, object_key, connection_params, table_name, file_name):
    """Process a single CSV file"""
    row_count = 0
    connection = None
    
    try:
        # Validate file type
        if not object_key.lower().endswith('.csv'):
            logger.warning(f"Skipping non-CSV file: {object_key}")
            return {'status': 'skipped', 'reason': 'Not a CSV file'}
        
        # Download and parse CSV from S3
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        csv_content = response['Body'].read().decode('utf-8')
        csv_reader = csv.reader(StringIO(csv_content))
        
        # Get column names from CSV header
        columns = next(csv_reader)
        logger.info(f"CSV columns ({len(columns)}): {columns[:5]}{'...' if len(columns) > 5 else ''}")
        
        # Connect to RDS
        connection = pymysql.connect(**connection_params)
        
        with connection.cursor() as cursor:
            # Create table if it doesn't exist
            create_table_if_not_exists(cursor, table_name, columns)
            
            # Insert CSV data
            row_count = insert_csv_data(cursor, table_name, columns, csv_reader, 
                                       bucket_name, object_key)
            
            # Update processing status
            update_processing_status(cursor, table_name, file_name, row_count)
            
            logger.info(f"Successfully inserted {row_count} rows into {table_name}")
            
            return {
                'status': 'success',
                'rows_inserted': row_count,
                'columns_processed': len(columns)
            }
            
    except csv.Error as e:
        error_msg = f"CSV parsing error: {str(e)}"
        logger.error(f"{error_msg} for {object_key}")
        
        # Update error status in database if connection exists
        if connection:
            try:
                with connection.cursor() as cursor:
                    update_processing_status(cursor, table_name, file_name, 0, error_msg)
            except Exception as db_error:
                logger.error(f"Failed to update error status in DB: {str(db_error)}")
        
        return {'status': 'failed', 'error': error_msg}
        
    except Exception as e:
        error_msg = f"Processing error: {str(e)}"
        logger.error(f"{error_msg} for {object_key}")
        return {'status': 'failed', 'error': error_msg}
        
    finally:
        # Close database connection
        if connection:
            try:
                connection.close()
            except Exception as e:
                logger.error(f"Error closing database connection: {str(e)}")

def lambda_handler(event, context):
    """Main Lambda handler function"""
    logger.info(f"Lambda invoked with event: {json.dumps(event, default=str)}")
    logger.info(f"Lambda context: {context.aws_request_id}")
    
    # Get environment variables
    rds_secret_arn = os.environ.get('RDS_SECRET_ARN')
    database_name = os.environ.get('DATABASE_NAME', 'MyDatabase')
    table_name = os.environ.get('TABLE_NAME', 'UploadedData')
    state_machine_arn = os.environ.get('STATE_MACHINE_ARN', '')
    rds_instance_id = os.environ.get('RDS_INSTANCE_ID', 'MyRDSDatabase')
    region = os.environ.get('AWS_REGION', os.environ.get('REGION', 'us-east-1'))
    
    if not rds_secret_arn:
        raise ValueError("RDS_SECRET_ARN environment variable is required")
    
    # Initialize AWS clients
    s3_client = boto3.client('s3', region_name=region)
    
    # Get RDS credentials from Secrets Manager
    credentials = get_rds_credentials(rds_secret_arn, region)
    
    # Get RDS endpoint
    rds_host = credentials.get('host')
    if not rds_host:
        logger.info("RDS host not in secret, querying RDS API...")
        rds_host = get_rds_endpoint(rds_instance_id, region)
    
    # Prepare RDS connection parameters
    connection_params = {
        'host': rds_host,
        'user': credentials['username'],
        'password': credentials['password'],
        'database': database_name,
        'connect_timeout': 10,
        'charset': 'utf8mb4',
        'cursorclass': pymysql.cursors.DictCursor,
        'autocommit': False
    }
    
    results = []
    
    for record in event['Records']:
        bucket_name = record['s3']['bucket']['name']
        object_key = record['s3']['object']['key']
        file_name = object_key.split('/')[-1]
        
        logger.info(f"Processing S3 object: s3://{bucket_name}/{object_key}")
        
        # Process the CSV file
        file_result = process_csv_file(
            s3_client, bucket_name, object_key, 
            connection_params, table_name, file_name
        )
        
        result = {
            'bucket': bucket_name,
            'key': object_key,
            'file_name': file_name,
            'timestamp': datetime.utcnow().isoformat(),
            **file_result
        }
        
        # Trigger Step Functions workflow if ARN is provided and processing was successful
        if (state_machine_arn and state_machine_arn.strip() and 
            file_result.get('status') == 'success'):
            
            try:
                input_data = {
                    "bucket": bucket_name,
                    "key": object_key,
                    "file_name": file_name,
                    "database": database_name,
                    "table": table_name,
                    "rows_processed": file_result.get('rows_inserted', 0),
                    "columns_processed": file_result.get('columns_processed', 0),
                    "status": "success",
                    "timestamp": datetime.utcnow().isoformat(),
                    "lambda_request_id": context.aws_request_id,
                    "rds_instance": rds_instance_id,
                    "secret_arn": rds_secret_arn
                }
                
                # Generate unique execution name
                timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                execution_name = f"s3-upload-{timestamp}-{context.aws_request_id[:8]}"
                
                execution_arn = trigger_step_functions(
                    state_machine_arn, 
                    input_data, 
                    execution_name,
                    region
                )
                
                result['stepfunctions_execution_arn'] = execution_arn
                logger.info(f"Triggered Step Functions: {execution_arn}")
                
            except Exception as sf_error:
                logger.error(f"Failed to trigger Step Functions: {str(sf_error)}")
                result['stepfunctions_error'] = str(sf_error)
                if result['status'] == 'success':
                    result['status'] = 'partial_success'
        
        results.append(result)
    
    # Prepare response
    success_count = len([r for r in results if r.get('status') == 'success'])
    partial_count = len([r for r in results if r.get('status') == 'partial_success'])
    failed_count = len([r for r in results if r.get('status') == 'failed'])
    skipped_count = len([r for r in results if r.get('status') == 'skipped'])
    
    total_rows = sum([r.get('rows_inserted', 0) for r in results])
    
    response_body = {
        'message': 'CSV processing completed',
        'summary': {
            'total_files': len(event['Records']),
            'successful_files': success_count,
            'partial_success_files': partial_count,
            'failed_files': failed_count,
            'skipped_files': skipped_count,
            'total_rows_inserted': total_rows,
            'stepfunctions_triggered': len([r for r in results if 'stepfunctions_execution_arn' in r])
        },
        'results': results,
        'metadata': {
            'lambda_request_id': context.aws_request_id,
            'timestamp': datetime.utcnow().isoformat(),
            'rds_instance': rds_instance_id,
            'database': database_name,
            'table': table_name
        }
    }
    
    logger.info(f"Processing summary: {json.dumps(response_body['summary'], indent=2)}")
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': json.dumps(response_body, default=str)
    }

# For local testing (if needed)
if __name__ == "__main__":
    import sys
    
    # Configure logging for local testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Mock event for local testing
    mock_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {
                        "name": "test-bucket"
                    },
                    "object": {
                        "key": "test.csv"
                    }
                }
            }
        ]
    }
    
    # Set environment variables for testing
    os.environ['AWS_REGION'] = 'us-east-1'
    os.environ['RDS_SECRET_ARN'] = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:TestSecret'
    os.environ['DATABASE_NAME'] = 'TestDB'
    os.environ['TABLE_NAME'] = 'TestTable'
    os.environ['STATE_MACHINE_ARN'] = 'arn:aws:states:us-east-1:123456789012:stateMachine:TestStateMachine'
    os.environ['RDS_INSTANCE_ID'] = 'MyRDSDatabase'
    
    # Mock context
    class MockContext:
        aws_request_id = 'test-request-' + datetime.utcnow().strftime('%Y%m%d%H%M%S')
        function_name = 'S3ToRDSLoader'
        memory_limit_in_mb = '1024'
        invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789012:function:S3ToRDSLoader'
    
    # Test the handler
    try:
        result = lambda_handler(mock_event, MockContext())
        print("\n" + "="*80)
        print("LAMBDA EXECUTION RESULT:")
        print("="*80)
        print(json.dumps(result, indent=2, default=str))
        print("="*80)
    except Exception as e:
        print(f"\nERROR during execution: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)