import os
import json
import boto3
import psycopg2
import csv
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_creds(secret_arn):
    client = boto3.client('secretsmanager')
    resp = client.get_secret_value(SecretId=secret_arn)
    return json.loads(resp['SecretString'])

def lambda_handler(event, context):
    conn = None
    try:
        # Configuration
        secret_arn = os.environ['RDS_SECRET_ARN']
        host = os.environ['RDS_ENDPOINT']
        db_name = os.environ['DATABASE_NAME']
        table_name = os.environ['TABLE_NAME']
        sm_arn = os.environ['STATE_MACHINE_ARN']
        
        creds = get_creds(secret_arn)
        
        # Connect to RDS
        conn = psycopg2.connect(
            host=host,
            user=creds['username'],
            password=creds['password'],
            dbname=db_name,
            port=creds.get('port', 5432),
            connect_timeout=5
        )
        
        s3 = boto3.client('s3')
        for record in event['Records']:
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            
            # Read CSV from S3
            obj = s3.get_object(Bucket=bucket, Key=key)
            lines = obj['Body'].read().decode('utf-8').splitlines()
            reader = csv.reader(lines)
            header = next(reader)
            
            with conn.cursor() as cur:
                # Create table
                cols = ", ".join([f'"{h}" TEXT' for h in header])
                cur.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" (id SERIAL PRIMARY KEY, {cols})')
                
                # Insert data
                placeholders = ", ".join(['%s'] * len(header))
                insert_query = f'INSERT INTO "{table_name}" ({", ".join([f'"{h}"' for h in header])}) VALUES ({placeholders})'
                
                count = 0
                for row in reader:
                    if len(row) == len(header):
                        cur.execute(insert_query, row)
                        count += 1
                conn.commit()
                
                # Trigger Step Function
                if sm_arn:
                    boto3.client('stepfunctions').start_execution(
                        stateMachineArn=sm_arn,
                        input=json.dumps({"file": key, "rows": count})
                    )
        
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error: {e}")
        if conn: conn.rollback()
        raise e
    finally:
        if conn: conn.close()