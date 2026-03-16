# DataSourceTransform(in progress)


This project focuses on building a data pipeline that processes and sends information to a specific model endpoint. It uses an ETL workflow to prepare data for an XGBoost model (containerized via Docker), facilitating automated predictions within the target account.

Design:

Trigger Mechanism: An S3 event (new object creation or update) triggers an AWS Lambda function.

Initial Storage: The Lambda function stores the incoming data in Amazon RDS as the first persistence layer.

Orchestration: An AWS Step Function orchestrates the workflow by initiating an AWS Glue job to process the data stored in S3.

Data Processing: The Glue job prepares and transforms the data before handing it off to an Apache Spark script running on Amazon EMR.

Final Delivery: The Spark script partitions the processed data and sends it in batches to an external prediction/model endpoint in a target account, which is implemented via the repository: https://github.com/ruihukuang/xgboost_model_docker_image.

