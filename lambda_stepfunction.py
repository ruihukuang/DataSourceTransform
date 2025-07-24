import os
import json
import boto3

def lambda_handler(event, context):
    # Initialize the Step Functions client
    stepfunctions_client = boto3.client('stepfunctions')
    
    # Retrieve region and account ID from environment variables
    region = os.environ['REGION']
    account_id = os.environ['ACCOUNT_ID']
    
    # Extract the bucket name and object key from the S3 event
    for record in event['Records']:
        bucket_name = record['s3']['bucket']['name']
        object_key = record['s3']['object']['key']
        
        # Log the bucket and object key
        print(f"New or updated object in S3: {bucket_name}/{object_key}")
        
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
        print(f"Step Functions execution started: {response["executionArn"]}")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Step Functions execution triggered successfully!')
    }
