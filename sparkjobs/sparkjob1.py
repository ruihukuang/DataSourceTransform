from pyspark.sql import SparkSession
import requests
import sys
def main(s3_path, endpoint_url, partition_number):
    # Initialize Spark session
    spark = SparkSession.builder \
        .appName("PartitionAndSendData") \
        .getOrCreate()
    # Read data from S3
    df = spark.read.csv(s3_path, header=True, inferSchema=True)
    # Partition the data
    partitioned_df = df.repartition(partition_number)
    # Process the data (example: filter and select specific columns)
    processed_df = partitioned_df.filter(df['value'] > 100).select('category', 'value')
    # Convert DataFrame to Pandas for sending via HTTP
    pandas_df = processed_df.toPandas()
    # Send data to the endpoint in batches
    batch_size = 10  # Number of rows per request
    for start in range(0, len(pandas_df), batch_size):
        batch = pandas_df.iloc[start:start + batch_size]
        data = batch.to_dict(orient='records')
        response = requests.post(endpoint_url, json=data, verify=True)  # SSL verification
        if response.status_code == 200:
            print(f"Successfully sent batch starting at index {start}")
        else:
            print(f"Failed to send batch starting at index {start}, Status Code: {response.status_code}")
    # Stop the Spark session
    spark.stop()
if __name__ == "__main__":
    # Get arguments from spark-submit
    s3_path = sys.argv[1]
    endpoint_url = sys.argv[2]
    partition_number = int(sys.argv[3])
    main(s3_path, endpoint_url, partition_number)
