# DataSourceTransform(in progress)


This project is to create a data pipeline to provide input data in a target account related to the project via the link https://github.com/ruihukuang/xgboost_model_docker_image.  

Design:

Trigger Mechanism: An S3 event (new object creation or update) triggers an AWS Lambda function.

Initial Storage: The Lambda function stores the incoming data in Amazon RDS as the first persistence layer.

Orchestration: An AWS Step Function orchestrates the workflow by initiating an AWS Glue job to process the data stored in S3.

Data Processing: The Glue job prepares and transforms the data before handing it off to an Apache Spark script running on Amazon EMR.

Final Delivery: The Spark script partitions the processed data and sends it in batches to an external prediction endpoint, which is implemented via the repository: https://github.com/ruihukuang/xgboost_model_docker_image.
