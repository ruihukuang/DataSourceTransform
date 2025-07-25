

spark-submit \
    --conf spark.driver.memory=12G \
    --conf spark.dynamicAllocation.enabled=false \
    --conf spark.kryoserializer.buffer.max=512 \
    --conf spark.rdd.compress=true \
    --conf spark.serializer=org.apache.spark.serializer.KryoSerializer \
    --conf spark.sql.parquet.writeLegacyFormat=true \
    --conf spark.task.maxFailures=30 \
    --conf spark.yarn.max.executor.failures=200 \
    --conf spark.executor.extraJavaOptions="-XX:+UseG1GC" \
    --conf spark.sql.hive.caseSensitiveInferenceMode=NEVER_INFER \
    --conf spark.sql.parquet.int96RebaseModeInRead=CORRECTED \
    --conf spark.yarn.maxAppAttempts=1 \
    --conf spark.sql.parquet.enableVectorizedReader=false \
    --conf spark.sql.parquet.int96RebaseModeInWrite=CORRECTED \
    --conf spark.sql.legacy.timeParserPolicy=LEGACY \
    --py-files s3://your-bucket/path/to/your-library.zip
    --master ${MASTER} \
    --deploy-mode cluster \
    --executor-memory 12G \
    --executor-cores 3 \
    --num-executors 100 \
    s3://your-bucket/path/to/your-spark-job.py \
    s3://your-bucket/path/to/data \
    https://your-endpoint.com/api/data \
    10
