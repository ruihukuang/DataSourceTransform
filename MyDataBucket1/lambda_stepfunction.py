import os
import json
import boto3
import psycopg2
import csv
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_creds(secret_arn):
    """Retrieves DB credentials from Secrets Manager."""
    client = boto3.client('secretsmanager')
    try:
        response = client.get_secret_value(SecretId=secret_arn)
        return json.loads(response['SecretString'])
    except Exception as e:
        logger.error(f"Failed to retrieve secret: {str(e)}")
        raise

def lambda_handler(event, context):
    connection = None
    try:
        # Load Environment Variables
        secret_arn = os.environ['RDS_SECRET_ARN']
        host = os.environ['RDS_ENDPOINT']
        db_name = os.environ['DATABASE_NAME']
        table_name = os.environ['TABLE_NAME']
        sm_arn = os.environ['STATE_MACHINE_ARN']
        
        creds = get_creds(secret_arn)
        
        # Connect to RDS PostgreSQL
        connection = psycopg2.connect(
            host=host,
            user=creds['username'],
            password=creds['password'],
            dbname=db_name,
            port=creds.get('port', 5432),
            connect_timeout=10
        )
        connection.autocommit = True # Standard for simple inserts

        s3 = boto3.client('s3')
        sf_client = boto3.client('stepfunctions')

        for record in event['Records']:
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            
            logger.info(f"Processing file: s3://{bucket}/{key}")
            
            # Read CSV
            obj = s3.get_object(Bucket=bucket, Key=key)
            lines = obj['Body'].read().decode('utf-8').splitlines()
            reader = csv.reader(lines)
            header = next(reader)

            with connection.cursor() as cursor:
                # 1. Dynamically create table if it doesn't exist
                # id, file_metadata columns + CSV columns
                col_defs = ", ".join([f'"{h.strip()}" TEXT' for h in header])
                create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" (id SERIAL PRIMARY KEY, load_file TEXT, {col_defs})'
                cursor.execute(create_sql)
                
                # 2. Bulk Insert
                col_names = ", ".join([f'"{h.strip()}"' for h in header])
                placeholders = ", ".join(['%s'] * (len(header) + 1))
                insert_sql = f'INSERT INTO "{table_name}" (load_file, {col_names}) VALUES ({placeholders})'
                
                rows_processed = 0
                for row in reader:
                    if len(row) == len(header):
                        cursor.execute(insert_sql, [key] + row)
                        rows_processed += 1
                
                logger.info(f"Successfully loaded {rows_processed} rows.")

                # 3. Trigger Step Function
                if sm_arn:
                    sf_client.start_execution(
                        stateMachineArn=sm_arn,
                        input=json.dumps({
                            "status": "COMPLETED",
                            "file_processed": key,
                            "rows_count": rows_processed
                        })
                    )

        return {"statusCode": 200, "body": "Processing Complete"}

    except Exception as e:
        logger.error(f"Critical Error: {str(e)}")
        raise e
    finally:
        if connection:
            connection.close()
            logger.info("RDS Connection closed.")