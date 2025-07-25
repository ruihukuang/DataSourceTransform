import os
import json
import boto3
import csv
from io import StringIO

def process_csv_file(s3_client, bucket_name, object_key, output_bucket):
    # Read CSV from S3
    csv_obj = s3_client.get_object(Bucket=bucket_name, Key=object_key)
    csv_content = csv_obj['Body'].read().decode('utf-8')
    csv_reader = csv.reader(StringIO(csv_content))
    
    # Convert CSV to list
    csv_data = list(csv_reader)
    
    # Extract column names
    column_names = csv_data[0]
    
    # Initialize data with the first two rows
    data = csv_data[1:3]
    
    # Generate additional rows
    for i in range(2, 100):
        new_row = []
        for j in range(len(column_names)):
            # Calculate new value as the sum of the last two rows
            new_value = float(data[i-1][j]) + float(data[i-2][j])
            new_row.append(new_value)
        data.append(new_row)
    
    # Convert data back to CSV format
    output = StringIO()
    csv_writer = csv.writer(output)
    csv_writer.writerow(column_names)
    csv_writer.writerows(data)
    
    # Write the result back to S3
    output_key = f'output/processed_{os.path.basename(object_key)}'
    s3_client.put_object(Bucket=output_bucket, Key=output_key, Body=output.getvalue())
    print(f"Processed file {object_key} and saved to {output_key}")

def main():
    # Retrieve environment variables
    input_bucket = os.environ['ENV_INPUT_BUCKET']
    output_bucket = os.environ['ENV_OUTPUT_BUCKET']
    
    # S3 client
    s3_client = boto3.client('s3')
    
    # List all objects in the input bucket
    response = s3_client.list_objects_v2(Bucket=input_bucket)
    
    # Process each CSV file in the bucket
    for obj in response.get('Contents', []):
        object_key = obj['Key']
        if object_key.endswith('.csv'):
            process_csv_file(s3_client, input_bucket, object_key, output_bucket)

if __name__ == "__main__":
    main()
