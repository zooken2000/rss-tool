"""
AWS Daily Digest — CDK スタック

cdk deploy 1回で以下をすべて作成します:
  1. ECR Repository          — AgentCore 用 Docker イメージ保存先
  2. CodeBuild Project        — ARM64 イメージをビルドして ECR に push
  3. Lambda (カスタムリソース) — CodeBuild 完了まで待機
  4. AgentCore Runtime        — Strands Agent のホスティング環境
  5. Lambda (handler)         — AgentCore 呼び出し + Slack 通知
  6. EventBridge × 2          — 朝9時（morning）・昼12時（noon）スケジュール

Slack 認証情報は CfnParameter で受け取り Lambda 環境変数に設定（Secrets Manager 不使用）
"""

import os
from aws_cdk import (
    CfnOutput,
    CfnParameter,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrockagentcore as bedrockagentcore,
    aws_codebuild as codebuild,
    aws_ecr as ecr,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3_assets as s3_assets,
)
from constructs import Construct

from stacks.infra_utils.agentcore_role import AgentCoreRole


class AwsDigestStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # Slack 認証情報（cdk deploy 時にパラメータとして渡す）
        slack_bot_token = CfnParameter(self, "SlackBotToken",
            type="String",
            no_echo=True,
            description="Slack Bot Token (xoxb-...)",
        )
        slack_channel_id = CfnParameter(self, "SlackChannelId",
            type="String",
            description="Slack チャンネル ID (C0XXXXXXXXX)",
        )

        # ─────────────────────────────────────────
        # 1. ECR Repository
        # ─────────────────────────────────────────
        ecr_repo = ecr.Repository(
            self,
            "AgentEcrRepo",
            repository_name="aws-digest-agent",
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            image_scan_on_push=True,
        )

        # ─────────────────────────────────────────
        # 2. CodeBuild — agent/ を ARM64 イメージにビルドして ECR に push
        # ─────────────────────────────────────────
        # agent/ ディレクトリを S3 にアップロードしてビルドソースとして使う
        agent_source = s3_assets.Asset(
            self,
            "AgentSource",
            path=os.path.join(os.path.dirname(__file__), "../../agent"),
        )

        codebuild_role = iam.Role(
            self,
            "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            inline_policies={
                "CodeBuildPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=[
                                f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/codebuild/*"
                            ],
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "ecr:GetAuthorizationToken",
                                "ecr:BatchCheckLayerAvailability",
                                "ecr:GetDownloadUrlForLayer",
                                "ecr:BatchGetImage",
                                "ecr:PutImage",
                                "ecr:InitiateLayerUpload",
                                "ecr:UploadLayerPart",
                                "ecr:CompleteLayerUpload",
                            ],
                            resources=[ecr_repo.repository_arn, "*"],
                        ),
                        iam.PolicyStatement(
                            actions=["s3:GetObject"],
                            resources=[f"{agent_source.bucket.bucket_arn}/*"],
                        ),
                    ]
                )
            },
        )

        build_project = codebuild.Project(
            self,
            "AgentBuildProject",
            project_name="aws-digest-agent-build",
            role=codebuild_role,
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
                compute_type=codebuild.ComputeType.LARGE,
                privileged=True,  # Docker ビルドに必要
            ),
            source=codebuild.Source.s3(
                bucket=agent_source.bucket,
                path=agent_source.s3_object_key,
            ),
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "aws ecr get-login-password --region $AWS_DEFAULT_REGION"
                            " | docker login --username AWS --password-stdin"
                            " $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com"
                        ]
                    },
                    "build": {
                        "commands": [
                            "docker build --platform linux/arm64 -t $IMAGE_REPO_NAME:latest .",
                            "docker tag $IMAGE_REPO_NAME:latest"
                            " $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$IMAGE_REPO_NAME:latest",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "docker push"
                            " $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$IMAGE_REPO_NAME:latest"
                        ]
                    },
                },
            }),
            environment_variables={
                "AWS_DEFAULT_REGION": codebuild.BuildEnvironmentVariable(value=self.region),
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=self.account),
                "IMAGE_REPO_NAME": codebuild.BuildEnvironmentVariable(value=ecr_repo.repository_name),
            },
        )

        # ─────────────────────────────────────────
        # 3. Lambda カスタムリソース — CodeBuild 完了まで待機
        # ─────────────────────────────────────────
        build_trigger_fn = lambda_.Function(
            self,
            "BuildTriggerFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="stacks.infra_utils.build_trigger_lambda.handler",
            timeout=Duration.minutes(15),
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), ".."),
                exclude=["*.pyc", "__pycache__", "cdk.out", ".venv"],
            ),
            initial_policy=[
                iam.PolicyStatement(
                    actions=["codebuild:StartBuild", "codebuild:BatchGetBuilds"],
                    resources=[build_project.project_arn],
                )
            ],
        )

        trigger_build = CustomResource(
            self,
            "TriggerAgentBuild",
            service_token=build_trigger_fn.function_arn,
            properties={"ProjectName": build_project.project_name},
        )

        # ─────────────────────────────────────────
        # 4. AgentCore Runtime
        # ─────────────────────────────────────────
        agent_role = AgentCoreRole(self, "AgentCoreRole")

        agent_runtime = bedrockagentcore.CfnRuntime(
            self,
            "AgentRuntime",
            agent_runtime_name="aws_digest_agent",
            agent_runtime_artifact=bedrockagentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=bedrockagentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=f"{ecr_repo.repository_uri}:latest"
                )
            ),
            network_configuration=bedrockagentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="HTTP",
            role_arn=agent_role.role_arn,
        )

        # CodeBuild 完了後に AgentCore を作成する
        agent_runtime.node.add_dependency(trigger_build)

        # ─────────────────────────────────────────
        # 5. Lambda — AgentCore 呼び出し + Slack 通知
        # ─────────────────────────────────────────
        lambda_role = iam.Role(
            self,
            "HandlerLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            inline_policies={
                "HandlerPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["bedrock-agentcore:InvokeAgentRuntime"],
                            resources=[agent_runtime.attr_agent_runtime_arn],
                        ),
                    ]
                )
            },
        )

        handler_fn = lambda_.Function(
            self,
            "HandlerFunction",
            function_name="aws-digest-handler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.handler",
            timeout=Duration.minutes(10),
            memory_size=256,
            role=lambda_role,
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "../../lambda"),
            ),
            environment={
                "AGENT_RUNTIME_ARN": agent_runtime.attr_agent_runtime_arn,
                "SLACK_BOT_TOKEN": slack_bot_token.value_as_string,
                "SLACK_CHANNEL_ID": slack_channel_id.value_as_string,
            },
        )

        # ─────────────────────────────────────────
        # 6. Lambda — 週次レポート（CloudWatch 収集 → LLM → Slack）
        # ─────────────────────────────────────────
        weekly_report_model_id = CfnParameter(self, "ReportModelId",
            type="String",
            default="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            description="週次レポート生成に使用する Bedrock モデル ID",
        )

        weekly_role = iam.Role(
            self,
            "WeeklyReportLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            inline_policies={
                "WeeklyReportPolicy": iam.PolicyDocument(
                    statements=[
                        # Lambda メトリクス取得（AWS/Lambda 名前空間）
                        iam.PolicyStatement(
                            actions=["cloudwatch:GetMetricStatistics"],
                            resources=["*"],
                        ),
                        # Logs Insights クエリ（ハンドラーログ + 将来の評価結果ログ）
                        iam.PolicyStatement(
                            actions=["logs:StartQuery"],
                            resources=[
                                f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/lambda/{handler_fn.function_name}",
                                f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/evaluations/results/*",
                            ],
                        ),
                        iam.PolicyStatement(
                            actions=["logs:GetQueryResults", "logs:StopQuery"],
                            resources=["*"],
                        ),
                        # Bedrock InvokeModel（レポート生成用 Claude）
                        iam.PolicyStatement(
                            actions=["bedrock:InvokeModel"],
                            resources=[
                                f"arn:aws:bedrock:{self.region}::foundation-model/*",
                            ],
                        ),
                    ]
                )
            },
        )

        weekly_fn = lambda_.Function(
            self,
            "WeeklyReportFunction",
            function_name="aws-digest-weekly-report",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="weekly_report.handler",
            timeout=Duration.minutes(5),
            memory_size=256,
            role=weekly_role,
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "../../lambda"),
            ),
            environment={
                "SLACK_BOT_TOKEN":        slack_bot_token.value_as_string,
                "SLACK_CHANNEL_ID":       slack_channel_id.value_as_string,
                "HANDLER_FUNCTION_NAME":  handler_fn.function_name,
                "EVAL_LOG_GROUP":         "",   # Online Evaluation 設定後に手動で更新
                "REPORT_MODEL_ID":        weekly_report_model_id.value_as_string,
            },
        )

        # ─────────────────────────────────────────
        # 7. EventBridge — 朝9時・昼12時（JST）
        # ─────────────────────────────────────────

        # 朝 9:00 JST = 00:00 UTC — What's New 速報
        events.Rule(
            self,
            "MorningRule",
            rule_name="aws-digest-morning",
            description="AWS Daily Digest — 朝9時 What's New 速報",
            schedule=events.Schedule.cron(hour="0", minute="0"),
            targets=[
                targets.LambdaFunction(
                    handler_fn,
                    event=events.RuleTargetInput.from_object({"mode": "morning"}),
                )
            ],
        )

        # 昼 12:00 JST = 03:00 UTC — 技術ブログまとめ
        events.Rule(
            self,
            "NoonRule",
            rule_name="aws-digest-noon",
            description="AWS Daily Digest — 昼12時 技術ブログまとめ",
            schedule=events.Schedule.cron(hour="3", minute="0"),
            targets=[
                targets.LambdaFunction(
                    handler_fn,
                    event=events.RuleTargetInput.from_object({"mode": "noon"}),
                )
            ],
        )

        # 週次レポート — 月曜 10:00 JST = 月曜 01:00 UTC
        # 朝の digest（00:00 UTC）完了後に実行するため 1時間ずらす
        events.Rule(
            self,
            "WeeklyReportRule",
            rule_name="aws-digest-weekly-report",
            description="AWS Daily Digest — 週次レポート（月曜 10:00 JST）",
            schedule=events.Schedule.cron(hour="1", minute="0", week_day="MON"),
            targets=[targets.LambdaFunction(weekly_fn)],
        )

        # ─────────────────────────────────────────
        # Outputs
        # ─────────────────────────────────────────
        CfnOutput(self, "AgentRuntimeArn",
                  description="AgentCore Runtime ARN",
                  value=agent_runtime.attr_agent_runtime_arn)
        CfnOutput(self, "HandlerFunctionName",
                  description="Lambda 関数名",
                  value=handler_fn.function_name)
        CfnOutput(self, "WeeklyReportFunctionName",
                  description="週次レポート Lambda 関数名",
                  value=weekly_fn.function_name)
        CfnOutput(self, "OnlineEvalSetupCommand",
                  description="Online Evaluation 設定コマンド（デプロイ後に実行）",
                  value=(
                      f"agentcore eval online create"
                      f" --name aws_digest_eval"
                      f" --sampling-rate 100"
                      f" --evaluator Builtin.GoalSuccessRate"
                      f" --evaluator Builtin.Helpfulness"
                      f" --evaluator Builtin.Correctness"
                  ))
