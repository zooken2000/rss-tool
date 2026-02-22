"""
CloudFormation カスタムリソース用 Lambda
CodeBuild のビルド（ARM64 Dockerイメージ）を起動し、完了まで待機する
"""
import json
import logging
import time
import urllib3
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class cfnresponse:
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

    @staticmethod
    def send(event, context, status, data, physical_id=None):
        body = json.dumps({
            "Status": status,
            "Reason": f"CloudWatch Log: {context.log_stream_name}",
            "PhysicalResourceId": physical_id or context.log_stream_name,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": data,
        })
        http = urllib3.PoolManager()
        http.request(
            "PUT",
            event["ResponseURL"],
            headers={"content-type": "", "content-length": str(len(body))},
            body=body,
        )


def handler(event, context):
    logger.info("Event: %s", json.dumps(event))

    try:
        # スタック削除時は何もしない
        if event["RequestType"] == "Delete":
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return

        project_name = event["ResourceProperties"]["ProjectName"]
        codebuild = boto3.client("codebuild")

        # ビルド開始
        build_id = codebuild.start_build(projectName=project_name)["build"]["id"]
        logger.info("Build started: %s", build_id)

        # タイムアウトまで待機（Lambda の残り時間 - 30秒）
        deadline = context.get_remaining_time_in_millis() / 1000 - 30
        start = time.time()

        while True:
            if time.time() - start > deadline:
                cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": "Build timeout"})
                return

            status = codebuild.batch_get_builds(ids=[build_id])["builds"][0]["buildStatus"]
            logger.info("Build status: %s", status)

            if status == "SUCCEEDED":
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {"BuildId": build_id})
                return
            elif status in ("FAILED", "FAULT", "STOPPED", "TIMED_OUT"):
                cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": f"Build {status}"})
                return

            time.sleep(30)

    except Exception as e:
        logger.error("Error: %s", str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": str(e)})
