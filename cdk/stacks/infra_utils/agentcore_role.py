from aws_cdk import aws_iam as iam, Stack
from constructs import Construct


class AgentCoreRole(iam.Role):
    """Strands Agent が AgentCore Runtime 上で動作するための IAM ロール"""

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        region = Stack.of(scope).region
        account = Stack.of(scope).account

        super().__init__(
            scope,
            construct_id,
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "AgentCorePolicy": iam.PolicyDocument(
                    statements=[
                        # ECR イメージ取得
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ecr:BatchGetImage",
                                "ecr:GetDownloadUrlForLayer",
                                "ecr:BatchCheckLayerAvailability",
                            ],
                            resources=[f"arn:aws:ecr:{region}:{account}:repository/*"],
                        ),
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["ecr:GetAuthorizationToken"],
                            resources=["*"],
                        ),
                        # Bedrock モデル呼び出し（Claude）
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                            ],
                            resources=[
                                "arn:aws:bedrock:*::foundation-model/*",
                                f"arn:aws:bedrock:{region}:{account}:*",
                            ],
                        ),
                        # CloudWatch Logs
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                                "logs:DescribeLogGroups",
                                "logs:DescribeLogStreams",
                            ],
                            resources=[
                                f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"
                            ],
                        ),
                        # X-Ray トレーシング
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "xray:PutTraceSegments",
                                "xray:PutTelemetryRecords",
                                "xray:GetSamplingRules",
                                "xray:GetSamplingTargets",
                            ],
                            resources=["*"],
                        ),
                        # CloudWatch メトリクス
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["cloudwatch:PutMetricData"],
                            resources=["*"],
                            conditions={
                                "StringEquals": {
                                    "cloudwatch:namespace": "bedrock-agentcore"
                                }
                            },
                        ),
                        # AgentCore ワークロードトークン
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock-agentcore:GetWorkloadAccessToken",
                                "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                            ],
                            resources=[
                                f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
                                f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/workload-identity/*",
                            ],
                        ),
                    ]
                )
            },
            **kwargs,
        )
