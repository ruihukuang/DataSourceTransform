import os
import json
import boto3
import pymysql
import csv
from io import StringIO

def lambda_handler(event, context):
    # Initialize the Step Functions and Secrets Manager clients
    stepfunctions_client = boto3.client('stepfunctions')
    secrets_client = boto3.client('secretsmanager')
    s3_client = boto3.client('s3')
    
    # Retrieve region and account ID from environment variables
    region = os.environ['REGION']
    account_id = os.environ['ACCOUNT_ID']
    rds_secret_arn = os.environ['RDS_SECRET_ARN']
    
    # Retrieve RDS credentials from Secrets Manager
    secret_response = secrets_client.get_secret_value(SecretId=rds_secret_arn)
    secret_string = secret_response['SecretString']
    secret = json.loads(secret_string)
    
    rds_host = 'your-rds-endpoint'  # Replace with your RDS endpoint
    rds_username = secret['username']
    rds_password = secret['password']
    rds_db_name = 'your-database-name'  # Replace with your database name
    
    # Extract the bucket name and object key from the S3 event
    for record in event['Records']:
        bucket_name = record['s3']['bucket']['name']
        object_key = record['s3']['object']['key']
        
        # Log the bucket and object key
        print(f"New or updated object in S3: {bucket_name}/{object_key}")
        
        # Load CSV data from S3
        try:
            csv_file = s3_client.get_object(Bucket=bucket_name, Key=object_key)
            csv_content = csv_file['Body'].read().decode('utf-8')
            csv_reader = csv.reader(StringIO(csv_content))
            
            # Connect to the RDS instance
            connection = pymysql.connect(
                host=rds_host,
                user=rds_username,
                password=rds_password,
                database=rds_db_name
            )
            
            with connection.cursor() as cursor:
                # Get the column names from the first row of the CSV
                columns = next(csv_reader)
                columns_placeholder = ', '.join(columns)
                values_placeholder = ', '.join(['%s'] * len(columns))
                
                # Insert each row into the RDS table
                for row in csv_reader:
                    sql = f"INSERT INTO your_table_name ({columns_placeholder}) VALUES ({values_placeholder})"
                    cursor.execute(sql, row)
            
            connection.commit()
            print("Data inserted into RDS successfully.")
        
        except Exception as e:
            print(f"Error inserting data into RDS: {e}")
        
        finally:
            connection.close()
        
        # Define the input for the Step Functions state machine
        input_data = {
            "Bucket": bucket_name,
            "Key": object_key
        }
        
        # Start the Step Functions execution
        response = stepfunctions_client.start_execution(
            stateMachineArn=f'arn:aws:states:{region}:{account_id}:stateMachine:YourStateMachineName',
            input=json.dumps(input_data)
        )
        
        # Log the response from Step Functions
        print(f"Step Functions execution started: {response['executionArn']}")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Step Functions execution triggered successfully!')
    }
