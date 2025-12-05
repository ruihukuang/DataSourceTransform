# DataSourceTransform(in progress)


This project is to create a data pipeline to provide input data in a target account related to the project via the link https://github.com/ruihukuang/xgboost_model_docker_image.  
Design: process data in S3 using Glue after saving data in RDS, use Lamda to partition data and send data in batches to an endpoint when there is a new object or an updated existing object in S3. The related AWS services include EMR, S3, Glue, Step Function, RDS, Lamda, Secret manager.
