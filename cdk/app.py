#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.aws_digest_stack import AwsDigestStack

app = cdk.App()
AwsDigestStack(app, "AwsDigestStack")
app.synth()
