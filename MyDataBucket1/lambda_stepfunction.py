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
    """Get Aurora credentials from Secrets Manager"""
    secrets_client = boto3.client('secretsmanager', region_name=region) if region else boto3.client('secretsmanager')
    try:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response.get('SecretString') or response.get('SecretBinary').decode('utf-8'))
        
        return {
            'username': secret.get('username'),
            'password': secret.get('password'),
            'host': secret.get('host'),  # We will prioritize the env var over this
            'database': secret.get('dbname', 'MyDatabase'),
            'port': int(secret.get('port', 3306))
        }
    except Exception as e:
        logger.error(f"Error retrieving secret {secret_arn}: {str(e)}")
        raise

def create_table_if_not_exists(cursor, table_name, columns):
    """Create table with dynamic columns for Aurora"""
    column_definitions = [f"`{col.strip().replace('`', '')}` TEXT" for col in columns]
    
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
        id INT AUTO_INCREMENT PRIMARY KEY,
        file_name VARCHAR(255),
        s3_bucket VARCHAR(255),
        s3_key VARCHAR(500),
        upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        processed BOOLEAN DEFAULT FALSE,
        rows_count INT DEFAULT 0,
        {', '.join(column_definitions)}
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """
    cursor.execute(create_table_sql)

def lambda_handler(event, context):
    logger.info(f"Invoked with event: {json.dumps(event)}")
    
    # 1. Get Environment Variables
    # Note: We use RDS_CLUSTER_ENDPOINT now instead of looking up an Instance ID
    cluster_endpoint = os.environ.get('RDS_CLUSTER_ENDPOINT')
    secret_arn = os.environ.get('RDS_SECRET_ARN')
    db_name = os.environ.get('DATABASE_NAME', 'MyDatabase')
    table_name = os.environ.get('TABLE_NAME', 'UploadedData')
    sm_arn = os.environ.get('STATE_MACHINE_ARN')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # 2. Get Credentials
    creds = get_rds_credentials(secret_arn, region)
    
    # Prioritize the endpoint passed from CloudFormation
    host = cluster_endpoint if cluster_endpoint else creds.get('host')

    connection = pymysql.connect(
        host=host,
        user=creds['username'],
        password=creds['password'],
        database=db_name,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )

    try:
        s3 = boto3.client('s3')
        for record in event['Records']:
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            
            # Read CSV
            resp = s3.get_object(Bucket=bucket, Key=key)
            lines = resp['Body'].read().decode('utf-8').splitlines()
            reader = csv.reader(lines)
            header = next(reader)

            with connection.cursor() as cursor:
                # Setup Table
                create_table_if_not_exists(cursor, table_name, header)
                
                # Bulk Insert
                insert_sql = f"INSERT INTO `{table_name}` (file_name, s3_bucket, s3_key, {', '.join([f'`{h}`' for h in header])}) VALUES (%s, %s, %s, {', '.join(['%s']*len(header))})"
                
                rows_inserted = 0
                for row in reader:
                    if len(row) == len(header):
                        cursor.execute(insert_sql, [key.split('/')[-1], bucket, key] + row)
                        rows_inserted += 1
                
                connection.commit()

                # 3. Trigger Step Functions
                if sm_arn:
                    sf = boto3.client('stepfunctions')
                    sf.start_execution(
                        stateMachineArn=sm_arn,
                        input=json.dumps({
                            "status": "success",
                            "file": key,
                            "rows": rows_inserted
                        })
                    )
                    
        return {"statusCode": 200, "body": "Processed successfully"}

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        if connection: connection.rollback()
        raise e
    finally:
        if connection: connection.close()