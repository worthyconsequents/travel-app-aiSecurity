"""CloudFormation factories for isolated, authenticated AWS demo copies."""

import hashlib


def ref(name):
    return {"Ref": name}


def sub(value):
    return {"Fn::Sub": value}


def att(name, attribute="Arn"):
    return {"Fn::GetAtt": [name, attribute]}


def resource(kind, properties, why, must=(), **extra):
    return {
        "Type": "AWS::" + kind,
        "Properties": properties,
        "Metadata": {"com.aws.cloudformation.Context": {"why": why, "must": list(must)}},
        **extra,
    }


def template(description):
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": description,
        "Metadata": {
            "AWSToolsMetrics": {"AWSAgentToolkit": "aws-cloudformation@3"},
            "com.aws.cloudformation.Context": {
                "ref": [
                    {
                        "at": "docs/aws-multi-deployment.md",
                        "has": "fleet architecture and lifecycle",
                    }
                ],
                "must": ["One copy per stack namespace; never embed credentials"],
            },
        },
        "Resources": {},
        "Outputs": {},
    }


def policy(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def allow(actions, resources):
    return {"Effect": "Allow", "Action": actions, "Resource": resources}


def trust(service, source=False):
    statement = {"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}
    if source:
        statement["Condition"] = {"StringEquals": {"aws:SourceAccount": ref("AWS::AccountId")}}
        if service == "bedrock-agentcore.amazonaws.com":
            statement["Condition"]["ArnLike"] = {
                "aws:SourceArn": sub(
                    "arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:"
                    "${AWS::AccountId}:gateway/*"
                )
            }
        elif service == "ecs-tasks.amazonaws.com":
            statement["Condition"]["ArnLike"] = {
                "aws:SourceArn": sub("arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:*")
            }
    return policy([statement])


def role(name, service, statements, source=False):
    return resource(
        "IAM::Role",
        {
            "RoleName": name,
            "AssumeRolePolicyDocument": trust(service, source),
            **(
                {"Policies": [{"PolicyName": "ScopedAccess", "PolicyDocument": policy(statements)}]}
                if statements
                else {}
            ),
        },
        "Separate execution boundary; grants only this deployment's dependencies",
        ["Do not grant access to another copy or to the shared detection key from app roles"],
    )


def compact(name, suffix):
    digest = hashlib.sha256(name.encode()).hexdigest()[:6]
    return f"{name[:21]}-{digest}-{suffix}"


def shared(config):
    t = template(
        "Boring Travel fleet artifacts; shared key remains externally owned and is never deleted here."
    )
    r = t["Resources"]
    r["Artifacts"] = resource(
        "S3::Bucket",
        {
            "BucketName": sub(
                compact(config.namespace, "art") + "-${AWS::AccountId}-${AWS::Region}"
            ),
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": {
                "ServerSideEncryptionConfiguration": [
                    {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            },
            "VersioningConfiguration": {"Status": "Enabled"},
        },
        "Content-addressed interceptor packages shared by copies",
        ["Keep artifacts after stack deletion; never put the vendor key in S3"],
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    r["ArtifactTLS"] = resource(
        "S3::BucketPolicy",
        {
            "Bucket": ref("Artifacts"),
            "PolicyDocument": policy(
                [
                    {
                        "Effect": "Deny",
                        "Principal": "*",
                        "Action": "s3:*",
                        "Resource": [att("Artifacts"), sub("${Artifacts.Arn}/*")],
                        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                    }
                ]
            ),
        },
        "Require transport encryption",
    )
    t["Outputs"]["ArtifactBucket"] = {"Value": ref("Artifacts")}
    for component in ("python", "frontend", "edge"):
        key = component.title() + "Repository"
        r[key] = resource(
            "ECR::Repository",
            {
                "RepositoryName": config.namespace + "-" + component,
                "ImageTagMutability": "IMMUTABLE",
                "ImageScanningConfiguration": {"ScanOnPush": True},
                "EncryptionConfiguration": {"EncryptionType": "AES256"},
                "EmptyOnDelete": False,
            },
            "Shared immutable app image; instances deploy exact digests",
            ["Preserve images used by other copies"],
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
        t["Outputs"][key] = {"Value": att(key, "RepositoryUri")}
    return t


def hosting(config, index):
    name = config.name(index)
    host, mcp_host = name + "." + config.domain, name + "-mcp." + config.domain
    t = template(
        "Isolated Boring Travel AWS lab: private Fargate and PostgreSQL, operator login, HTTPS and private MCP ingress."
    )
    t["Parameters"] = {
        k: {"Type": "String", "Default": ""}
        for k in ("ToolGatewayUrl", "InferenceGatewayUrl", "ToolGatewayArn", "InferenceGatewayArn")
    }
    t["Conditions"] = {
        "GatewaysBound": {
            "Fn::And": [
                {"Fn::Not": [{"Fn::Equals": [ref("ToolGatewayArn"), ""]}]},
                {"Fn::Not": [{"Fn::Equals": [ref("InferenceGatewayArn"), ""]}]},
            ]
        }
    }
    r = t["Resources"]
    r["Vpc"] = resource(
        "EC2::VPC",
        {
            "CidrBlock": f"10.{80 + index}.0.0/16",
            "EnableDnsSupport": True,
            "EnableDnsHostnames": True,
            "Tags": [{"Key": "Name", "Value": name}],
        },
        "Dedicated network per demo copy",
        ["No peering or database ingress from other copies"],
    )
    r["InternetGateway"] = resource(
        "EC2::InternetGateway", {}, "Internet path for ALB and NAT only"
    )
    r["Attachment"] = resource(
        "EC2::VPCGatewayAttachment",
        {"VpcId": ref("Vpc"), "InternetGatewayId": ref("InternetGateway")},
        "Attach isolated VPC internet gateway",
    )
    r["PublicRoutes"] = resource(
        "EC2::RouteTable", {"VpcId": ref("Vpc")}, "Public ALB and NAT routing"
    )
    r["PublicDefault"] = resource(
        "EC2::Route",
        {
            "RouteTableId": ref("PublicRoutes"),
            "GatewayId": ref("InternetGateway"),
            "DestinationCidrBlock": "0.0.0.0/0",
        },
        "Outbound public routing",
        DependsOn="Attachment",
    )
    r["PrivateRoutes"] = resource("EC2::RouteTable", {"VpcId": ref("Vpc")}, "Private task egress")
    for az in (0, 1):
        for tier, octet, table in (
            ("Public", az, "PublicRoutes"),
            ("Private", az + 10, "PrivateRoutes"),
        ):
            key = f"{tier}{az}"
            r[key] = resource(
                "EC2::Subnet",
                {
                    "VpcId": ref("Vpc"),
                    "CidrBlock": f"10.{80 + index}.{octet}.0/24",
                    "AvailabilityZone": {"Fn::Select": [az, {"Fn::GetAZs": ""}]},
                    "MapPublicIpOnLaunch": False,
                    "Tags": [{"Key": "Name", "Value": name + "-" + key.lower()}],
                },
                "Subnet in distinct availability zone",
            )
            r[key + "Route"] = resource(
                "EC2::SubnetRouteTableAssociation",
                {"SubnetId": ref(key), "RouteTableId": ref(table)},
                "Bind routing for this tier",
            )
    r["NatAddress"] = resource("EC2::EIP", {"Domain": "vpc"}, "Dedicated lab NAT address")
    r["Nat"] = resource(
        "EC2::NatGateway",
        {
            "AllocationId": att("NatAddress", "AllocationId"),
            "SubnetId": ref("Public0"),
        },
        "Single NAT for lab cost; not high availability",
        DependsOn="Attachment",
    )
    r["PrivateDefault"] = resource(
        "EC2::Route",
        {
            "RouteTableId": ref("PrivateRoutes"),
            "NatGatewayId": ref("Nat"),
            "DestinationCidrBlock": "0.0.0.0/0",
        },
        "Only outbound path; tasks never receive public addresses",
    )
    for key in ("PublicAlbSg", "PrivateAlbSg", "TaskSg", "DbSg", "LatticeSg"):
        ingress = []
        if key == "PublicAlbSg":
            ingress = [
                {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": config.allowed_cidr}
            ]
        r[key] = resource(
            "EC2::SecurityGroup",
            {
                "GroupDescription": name + "-" + key,
                "VpcId": ref("Vpc"),
                "SecurityGroupIngress": ingress,
                "SecurityGroupEgress": [{"IpProtocol": "-1", "CidrIp": "0.0.0.0/0"}],
                "Tags": [{"Key": "Name", "Value": name + "-" + key.lower()}],
            },
            "Copy-specific security boundary",
            ["Never add public task, MCP or DB ingress"],
        )
    for key, dest, source, port in (
        ("PublicToTask", "TaskSg", "PublicAlbSg", 8080),
        ("PrivateToTask", "TaskSg", "PrivateAlbSg", 8082),
        ("LatticeToAlb", "PrivateAlbSg", "LatticeSg", 443),
        ("TaskToDb", "DbSg", "TaskSg", 5432),
    ):
        r[key] = resource(
            "EC2::SecurityGroupIngress",
            {
                "GroupId": ref(dest),
                "SourceSecurityGroupId": ref(source),
                "IpProtocol": "tcp",
                "FromPort": port,
                "ToPort": port,
            },
            "Allow exactly the required tier-to-tier path",
        )
    for key, suffix, field in (
        ("DatabaseSecret", "database", "password"),
        ("MonitorSecret", "monitor", "password"),
        ("SigningSecret", "signing", "key"),
        ("IngressSecret", "mcp-ingress", "key"),
    ):
        r[key] = resource(
            "SecretsManager::Secret",
            {
                "Name": name + "-" + suffix,
                "GenerateSecretString": {
                    "SecretStringTemplate": "{}",
                    "GenerateStringKey": field,
                    "PasswordLength": 48,
                    "ExcludePunctuation": True,
                },
            },
            "Unique credentials per copy; generated inside Secrets Manager",
            ["Never reuse the shared vendor key for app authentication"],
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
    r["DbSubnets"] = resource(
        "RDS::DBSubnetGroup",
        {
            "DBSubnetGroupDescription": name,
            "SubnetIds": [ref("Private0"), ref("Private1")],
        },
        "Database private-only subnets",
    )
    r["DatabaseParameters"] = resource(
        "RDS::DBParameterGroup",
        {
            "Description": "Require encrypted PostgreSQL connections",
            "Family": "postgres17",
            "Parameters": {"rds.force_ssl": "1"},
        },
        "Reject plaintext database clients",
        ["Keep TLS enforcement enabled"],
    )
    r["Database"] = resource(
        "RDS::DBInstance",
        {
            "DBInstanceIdentifier": name + "-db",
            "Engine": "postgres",
            "EngineVersion": "17.11",
            "DBInstanceClass": "db.t4g.micro",
            "AllocatedStorage": "20",
            "StorageType": "gp3",
            "StorageEncrypted": True,
            "PubliclyAccessible": False,
            "DBName": "travel_demo",
            "MasterUsername": "travel_demo",
            "MasterUserPassword": sub(
                "{{resolve:secretsmanager:${DatabaseSecret}:SecretString:password}}"
            ),
            "DBSubnetGroupName": ref("DbSubnets"),
            "DBParameterGroupName": ref("DatabaseParameters"),
            "VPCSecurityGroups": [ref("DbSg")],
            "BackupRetentionPeriod": 1,
            "AutoMinorVersionUpgrade": True,
            "CopyTagsToSnapshot": True,
            "DeletionProtection": False,
            "MultiAZ": False,
        },
        "Dedicated encrypted PostgreSQL; lab single-AZ sizing",
        ["Snapshot database on teardown before removing its private network"],
        DeletionPolicy="Snapshot",
        UpdateReplacePolicy="Snapshot",
    )
    for key, internal in (("PublicAlb", False), ("PrivateAlb", True)):
        r[key] = resource(
            "ElasticLoadBalancingV2::LoadBalancer",
            {
                "Name": compact(name, "int" if internal else "web"),
                "Type": "application",
                "Scheme": "internal" if internal else "internet-facing",
                "Subnets": [
                    ref("Private0" if internal else "Public0"),
                    ref("Private1" if internal else "Public1"),
                ],
                "SecurityGroups": [ref("PrivateAlbSg" if internal else "PublicAlbSg")],
                "LoadBalancerAttributes": [
                    {"Key": "routing.http.drop_invalid_header_fields.enabled", "Value": "true"}
                ],
            },
            "Private tool ingress" if internal else "HTTPS operator entry point",
        )
        group = "PrivateTargets" if internal else "PublicTargets"
        r[group] = resource(
            "ElasticLoadBalancingV2::TargetGroup",
            {
                "VpcId": ref("Vpc"),
                "Port": 8082 if internal else 8080,
                "Protocol": "HTTP",
                "TargetType": "ip",
                "HealthCheckPath": "/health",
                "HealthyThresholdCount": 2,
                "TargetGroupAttributes": [
                    {"Key": "deregistration_delay.timeout_seconds", "Value": "30"}
                ],
            },
            "Only the NGINX ports are reachable from load balancers",
        )
    r["UserPool"] = resource(
        "Cognito::UserPool",
        {
            "UserPoolName": name + "-operators",
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
            "AutoVerifiedAttributes": ["email"],
            "UsernameAttributes": ["email"],
            "Policies": {
                "PasswordPolicy": {
                    "MinimumLength": 14,
                    "RequireLowercase": True,
                    "RequireUppercase": True,
                    "RequireNumbers": True,
                    "RequireSymbols": True,
                }
            },
        },
        "Operators must authenticate before reaching synthetic demo personas",
        ["No public self-registration; demo persona selection is not production customer identity"],
    )
    r["UserClient"] = resource(
        "Cognito::UserPoolClient",
        {
            "UserPoolId": ref("UserPool"),
            "ClientName": name + "-web",
            "GenerateSecret": True,
            "AllowedOAuthFlowsUserPoolClient": True,
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": ["openid", "email"],
            "SupportedIdentityProviders": ["COGNITO"],
            "CallbackURLs": [f"https://{host}/oauth2/idpresponse"],
            "LogoutURLs": [f"https://{host}/"],
            "EnableTokenRevocation": True,
            "PreventUserExistenceErrors": "ENABLED",
        },
        "Confidential ALB OAuth client; browser never receives its client secret",
    )
    r["UserDomain"] = resource(
        "Cognito::UserPoolDomain",
        {
            "Domain": sub(name + "-${AWS::AccountId}"),
            "UserPoolId": ref("UserPool"),
        },
        "Unique per-copy Cognito login endpoint",
    )
    r["PublicListener"] = resource(
        "ElasticLoadBalancingV2::Listener",
        {
            "LoadBalancerArn": ref("PublicAlb"),
            "Port": 443,
            "Protocol": "HTTPS",
            "Certificates": [{"CertificateArn": config.certificate}],
            "SslPolicy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
            "DefaultActions": [
                {
                    "Type": "authenticate-cognito",
                    "Order": 1,
                    "AuthenticateCognitoConfig": {
                        "UserPoolArn": att("UserPool"),
                        "UserPoolClientId": ref("UserClient"),
                        "UserPoolDomain": ref("UserDomain"),
                        "OnUnauthenticatedRequest": "authenticate",
                        "SessionCookieName": name + "-operator",
                        "SessionTimeout": 3600,
                    },
                },
                {"Type": "forward", "Order": 2, "TargetGroupArn": ref("PublicTargets")},
            ],
        },
        "Every public route requires login; no unauthenticated rule overrides",
    )
    r["PrivateListener"] = resource(
        "ElasticLoadBalancingV2::Listener",
        {
            "LoadBalancerArn": ref("PrivateAlb"),
            "Port": 443,
            "Protocol": "HTTPS",
            "Certificates": [{"CertificateArn": config.certificate}],
            "SslPolicy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
            "DefaultActions": [{"Type": "forward", "TargetGroupArn": ref("PrivateTargets")}],
        },
        "Private TLS MCP listener; service key checked again by NGINX",
    )
    for key, domain, lb in (("WebDns", host, "PublicAlb"), ("McpDns", mcp_host, "PrivateAlb")):
        r[key] = resource(
            "Route53::RecordSet",
            {
                "HostedZoneId": config.hosted_zone,
                "Name": domain,
                "Type": "A",
                "AliasTarget": {
                    "DNSName": att(lb, "DNSName"),
                    "HostedZoneId": att(lb, "CanonicalHostedZoneID"),
                },
            },
            "Distinct copy URL; MCP alias points only to private addresses",
        )
    r["AppLogs"] = resource(
        "Logs::LogGroup",
        {
            "LogGroupName": "/ecs/" + name,
            "RetentionInDays": 7,
        },
        "Copy-scoped container logs",
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    repo_arns = [
        sub(
            "arn:${AWS::Partition}:ecr:${AWS::Region}:${AWS::AccountId}:repository/"
            + image.split("/", 1)[-1].split("@")[0]
        )
        for image in (config.python_image, config.frontend_image, config.edge_image)
    ]
    r["ExecutionRole"] = role(
        name + "-execution",
        "ecs-tasks.amazonaws.com",
        [
            allow(["ecr:GetAuthorizationToken"], "*"),
            allow(["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], repo_arns),
            allow(["logs:CreateLogStream", "logs:PutLogEvents"], att("AppLogs")),
            allow(
                ["secretsmanager:GetSecretValue"],
                [
                    ref(k)
                    for k in ("DatabaseSecret", "MonitorSecret", "SigningSecret", "IngressSecret")
                ],
            ),
        ],
        source=True,
    )
    r["TaskRole"] = role(name + "-app", "ecs-tasks.amazonaws.com", [], source=True)
    r["GatewayInvocation"] = resource(
        "IAM::Policy",
        {
            "PolicyName": name + "-invoke",
            "Roles": [ref("TaskRole")],
            "PolicyDocument": policy(
                [
                    allow(
                        ["bedrock-agentcore:InvokeGateway"],
                        [ref("ToolGatewayArn"), ref("InferenceGatewayArn")],
                    )
                ]
            ),
        },
        "Only the bound gateways; no direct model or detection-secret access",
        Condition="GatewaysBound",
    )
    env = {
        "APP_MODE": "aws-demo",
        "AWS_REGION": config.region,
        "AWS_DEMO_EDGE_AUTH": "cognito-alb",
        "DEPLOYMENT_PROFILE": "agentcore-aws",
        "ENABLE_AWS_AGENTCORE": "true",
        "MODEL_MODE": "agentcore" if config.paid_inference else "mock",
        "ENABLE_PAID_INFERENCE": "true" if config.paid_inference else "false",
        "AGENTCORE_MODEL_ID": name + "-model/" + config.model_id.removeprefix("bedrock-mantle/"),
        "AGENTCORE_TARGET_PREFIX": name + "-",
        "AGENTCORE_TOOL_GATEWAY_URL": ref("ToolGatewayUrl"),
        "AGENTCORE_INFERENCE_GATEWAY_URL": ref("InferenceGatewayUrl"),
        "DATABASE_HOST": att("Database", "Endpoint.Address"),
        "SESSION_COOKIE_NAME": name + "-session",
        "MONITOR_COOKIE_SECURE": "true",
        "GATEWAY_URL": "http://127.0.0.1:8004",
    }
    secrets = [
        {"Name": "DATABASE_PASSWORD", "ValueFrom": sub("${DatabaseSecret}:password::")},
        {"Name": "MCP_SIGNING_KEY", "ValueFrom": sub("${SigningSecret}:key::")},
    ]
    containers = []
    for service, port in (
        ("api", 8000),
        ("gateway", 8004),
        ("travel-discovery", 8001),
        ("reservations", 8002),
        ("customer-payments", 8003),
    ):
        module = "services." + service if service in {"api", "gateway"} else "services.mcp_server"
        command = (
            [
                "uvicorn",
                module + ":app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--proxy-headers",
                "--forwarded-allow-ips",
                "127.0.0.1",
            ]
            if service in {"api", "gateway"}
            else ["python", "-m", module]
        )
        container = {
            "Name": service,
            "Image": config.python_image,
            "Essential": True,
            "Command": command,
            "Environment": [
                {"Name": k, "Value": v}
                for k, v in (env | {"SERVICE": service, "PORT": str(port)}).items()
            ],
            "Secrets": secrets
            + (
                [{"Name": "MONITOR_PASSWORD", "ValueFrom": sub("${MonitorSecret}:password::")}]
                if service == "api"
                else []
            ),
            "HealthCheck": {
                "Command": [
                    "CMD",
                    "python",
                    "-c",
                    "import urllib.request; "
                    f"urllib.request.urlopen('http://127.0.0.1:{port}/health')",
                ],
                "Interval": 15,
                "Timeout": 5,
                "Retries": 5,
                "StartPeriod": 60,
            },
        }
        containers.append(container)
    containers.append(
        {
            "Name": "frontend",
            "Image": config.frontend_image,
            "Essential": True,
            "HealthCheck": {
                "Command": [
                    "CMD",
                    "node",
                    "-e",
                    "fetch('http://127.0.0.1:3000/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
                ],
                "Interval": 15,
                "Timeout": 5,
                "Retries": 5,
                "StartPeriod": 60,
            },
        }
    )
    containers.append(
        {
            "Name": "edge",
            "Image": config.edge_image,
            "Essential": True,
            "PortMappings": [{"ContainerPort": 8080}, {"ContainerPort": 8082}],
            "Secrets": [{"Name": "MCP_SERVICE_KEY", "ValueFrom": sub("${IngressSecret}:key::")}],
            "DependsOn": [{"ContainerName": c["Name"], "Condition": "HEALTHY"} for c in containers],
            "HealthCheck": {
                "Command": ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/health"],
                "Interval": 15,
                "Timeout": 5,
                "Retries": 5,
                "StartPeriod": 60,
            },
        }
    )
    for c in containers:
        c["StopTimeout"] = 60
        c["LogConfiguration"] = {
            "LogDriver": "awslogs",
            "Options": {
                "awslogs-group": ref("AppLogs"),
                "awslogs-region": ref("AWS::Region"),
                "awslogs-stream-prefix": c["Name"],
            },
        }
    r["Cluster"] = resource("ECS::Cluster", {"ClusterName": name}, "Dedicated ECS cluster per copy")
    r["Task"] = resource(
        "ECS::TaskDefinition",
        {
            "Family": name,
            "NetworkMode": "awsvpc",
            "RequiresCompatibilities": ["FARGATE"],
            "Cpu": "2048",
            "Memory": "4096",
            "ExecutionRoleArn": att("ExecutionRole"),
            "TaskRoleArn": att("TaskRole"),
            "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"},
            "ContainerDefinitions": containers,
        },
        "One complete app task per copy; containers share a task trust boundary",
        ["Inspector must run outside this task; never inject shared detection key"],
    )
    r["Service"] = resource(
        "ECS::Service",
        {
            "ServiceName": name,
            "Cluster": ref("Cluster"),
            "TaskDefinition": ref("Task"),
            "DesiredCount": 1,
            "LaunchType": "FARGATE",
            "PlatformVersion": "1.4.0",
            "HealthCheckGracePeriodSeconds": 180,
            "DeploymentConfiguration": {
                "DeploymentCircuitBreaker": {"Enable": True, "Rollback": True}
            },
            "NetworkConfiguration": {
                "AwsvpcConfiguration": {
                    "AssignPublicIp": "DISABLED",
                    "Subnets": [ref("Private0"), ref("Private1")],
                    "SecurityGroups": [ref("TaskSg")],
                }
            },
            "LoadBalancers": [
                {"ContainerName": "edge", "ContainerPort": port, "TargetGroupArn": ref(tg)}
                for port, tg in ((8080, "PublicTargets"), (8082, "PrivateTargets"))
            ],
        },
        "Private complete app; rollback failed service deployments",
        DependsOn=["PublicListener", "PrivateListener", "PrivateDefault"],
    )
    t["Outputs"] = {
        k: {"Value": value}
        for k, value in {
            "VpcId": ref("Vpc"),
            "Subnet0": ref("Private0"),
            "Subnet1": ref("Private1"),
            "LatticeSecurityGroup": ref("LatticeSg"),
            "IngressSecretArn": ref("IngressSecret"),
            "MonitorSecretArn": ref("MonitorSecret"),
            "DatabaseId": ref("Database"),
            "UserPoolId": ref("UserPool"),
            "AppUrl": "https://" + host,
            "McpUrl": "https://" + mcp_host,
            "TaskRoleArn": att("TaskRole"),
        }.items()
    }
    return t


def agentcore(config, index, base=None, bucket=None, key=None, version=None):
    name = config.name(index)
    t = template(
        "Per-copy AgentCore gateways and inspector; only inspector can read the shared external Trend key."
    )
    if base is None:
        keys = ("IngressSecretArn", "McpUrl", "VpcId", "Subnet0", "Subnet1", "LatticeSecurityGroup")
        t["Parameters"] = {"Hosting" + k: {"Type": "String"} for k in keys}
        for k in ("ArtifactBucket", "ArtifactKey", "ArtifactVersion"):
            t["Parameters"][k] = {"Type": "String"}
        base = {k: ref("Hosting" + k) for k in keys}
        bucket, key, version = ref("ArtifactBucket"), ref("ArtifactKey"), ref("ArtifactVersion")
    r = t["Resources"]
    r["Logs"] = resource(
        "Logs::LogGroup",
        {
            "LogGroupName": "/aws/lambda/" + name + "-inspector",
            "RetentionInDays": 7,
        },
        "Inspector decision metadata only; no prompts or key values",
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    statements = [
        allow(["secretsmanager:GetSecretValue"], config.secret_arn),
        allow(["logs:CreateLogStream", "logs:PutLogEvents"], att("Logs")),
    ]
    if config.secret_kms_arn:
        statement = allow(["kms:Decrypt"], config.secret_kms_arn)
        statement["Condition"] = {
            "StringEquals": {
                "kms:ViaService": f"secretsmanager.{config.region}.amazonaws.com",
                "kms:EncryptionContext:SecretARN": config.secret_arn,
            }
        }
        statements.append(statement)
    r["InspectorRole"] = role(name + "-inspector", "lambda.amazonaws.com", statements)
    r["Inspector"] = resource(
        "Lambda::Function",
        {
            "FunctionName": name + "-inspector",
            "Runtime": "python3.12",
            "Handler": "services.agentcore.interceptor.lambda_handler",
            "Role": att("InspectorRole"),
            "Timeout": 15,
            "MemorySize": 256,
            "ReservedConcurrentExecutions": 2,
            "Code": {"S3Bucket": bucket, "S3Key": key, "S3ObjectVersion": version},
            "Environment": {
                "Variables": {
                    "AI_GUARD_MODE": "real",
                    "AI_GUARD_SECRET_ARN": config.secret_arn,
                    "AI_GUARD_URL": config.ai_guard_url,
                    "AI_GUARD_APPLICATION_NAME": name,
                    "AI_GUARD_ALLOWED_MODEL": name
                    + "-model/"
                    + config.model_id.removeprefix("bedrock-mantle/")
                    if config.paid_inference
                    else "INFERENCE_DISABLED",
                }
            },
        },
        "One inspector execution role per copy reading the exact same secret ARN",
        DependsOn="Logs",
    )
    r["IngressProvider"] = resource(
        "BedrockAgentCore::ApiKeyCredentialProvider",
        {
            "Name": name + "-mcp",
            "ApiKeySecretSource": "EXTERNAL",
            "ApiKeySecretConfig": {"SecretId": base["IngressSecretArn"], "JsonKey": "key"},
        },
        "Private MCP ingress key belongs to this copy; distinct from shared detection credential",
    )
    gateway_statements = [
        allow(["lambda:InvokeFunction"], att("Inspector")),
        allow(
            ["bedrock-agentcore:GetResourceApiKey"], att("IngressProvider", "CredentialProviderArn")
        ),
        allow(["secretsmanager:GetSecretValue"], base["IngressSecretArn"]),
        allow(["bedrock-agentcore:GetPolicyEngine"], att("PolicyEngine", "PolicyEngineArn")),
        allow(
            ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions"],
            [
                att("PolicyEngine", "PolicyEngineArn"),
                sub(
                    "arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:gateway/"
                    + name
                    + "-tools-*"
                ),
            ],
        ),
    ]
    if config.paid_inference:
        statement = allow(["bedrock-mantle:CreateInference"], config.model_resource)
        statement["Condition"] = {
            "StringEquals": {
                "bedrock-mantle:Model": config.model_id.removeprefix("bedrock-mantle/")
            }
        }
        gateway_statements.append(statement)
    r["GatewayRole"] = role(
        name + "-gateway", "bedrock-agentcore.amazonaws.com", gateway_statements, source=True
    )
    r["GatewayRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"][
        "ArnLike"
    ]["aws:SourceArn"] = sub(
        "arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:gateway/"
        + name
        + "-*"
    )
    r["PolicyEngine"] = resource(
        "BedrockAgentCore::PolicyEngine",
        {
            "Name": (name + "_policy").replace("-", "_"),
        },
        "Per-copy Cedar allowlist adds workload-level enforcement",
        ["Use ENFORCE; no mutation or bulk-record permit"],
    )
    # Both control-plane gateways always exist; model target exists only with explicit opt-in.
    for kind in ("Tools", "Inference"):
        props = {
            "Name": name + "-" + kind.lower(),
            "RoleArn": att("GatewayRole"),
            "AuthorizerType": "AWS_IAM",
            "InterceptorConfigurations": [
                {
                    "Interceptor": {"Lambda": {"Arn": att("Inspector")}},
                    "InterceptionPoints": ["REQUEST", "RESPONSE"],
                    "InputConfiguration": {"PassRequestHeaders": False},
                }
            ],
        }
        if kind == "Tools":
            props["ProtocolType"] = "MCP"
            props["ProtocolConfiguration"] = {"Mcp": {"SupportedVersions": ["2025-03-26"]}}
            props["PolicyEngineConfiguration"] = {
                "Arn": att("PolicyEngine", "PolicyEngineArn"),
                "Mode": "ENFORCE",
            }
        r[kind] = resource(
            "BedrockAgentCore::Gateway", props, "IAM-only gateway; fail closed on inspection errors"
        )
        r[kind + "Permission"] = resource(
            "Lambda::Permission",
            {
                "FunctionName": ref("Inspector"),
                "Action": "lambda:InvokeFunction",
                "Principal": "bedrock-agentcore.amazonaws.com",
                "SourceAccount": ref("AWS::AccountId"),
                "SourceArn": att(kind, "GatewayArn"),
            },
            "Only this gateway may invoke the inspector",
        )
    for server in ("travel-discovery", "reservations", "customer-payments"):
        r[server.title().replace("-", "") + "Target"] = resource(
            "BedrockAgentCore::GatewayTarget",
            {
                "GatewayIdentifier": att("Tools", "GatewayIdentifier"),
                "Name": name + "-" + server,
                "TargetConfiguration": {
                    "Mcp": {
                        "McpServer": {
                            "Endpoint": {"Fn::Join": ["", [base["McpUrl"], "/" + server + "/mcp"]]}
                        }
                    }
                },
                "PrivateEndpoint": {
                    "ManagedVpcResource": {
                        "VpcIdentifier": base["VpcId"],
                        "SubnetIds": [base["Subnet0"], base["Subnet1"]],
                        "SecurityGroupIds": [base["LatticeSecurityGroup"]],
                        "EndpointIpAddressType": "IPV4",
                    }
                },
                "CredentialProviderConfigurations": [
                    {
                        "CredentialProviderType": "API_KEY",
                        "CredentialProvider": {
                            "ApiKeyCredentialProvider": {
                                "ProviderArn": att("IngressProvider", "CredentialProviderArn"),
                                "CredentialLocation": "HEADER",
                                "CredentialParameterName": "X-MCP-Service-Key",
                            }
                        },
                    }
                ],
            },
            "Native MCP target through managed VPC Lattice, TLS and per-copy service key",
            DependsOn="ToolsPermission",
        )
    for server, tool in (
        ("travel-discovery", "search_hotels"),
        ("travel-discovery", "get_hotel_details"),
        ("travel-discovery", "search_flights"),
        ("reservations", "get_my_bookings"),
        ("customer-payments", "get_customer_profile"),
    ):
        r["Permit" + tool.title().replace("_", "")] = resource(
            "BedrockAgentCore::Policy",
            {
                "Name": "dannytran_" + hashlib.sha256(name.encode()).hexdigest()[:8] + "_" + tool,
                "PolicyEngineId": att("PolicyEngine", "PolicyEngineId"),
                "EnforcementMode": "ACTIVE",
                "ValidationMode": "FAIL_ON_ANY_FINDINGS",
                "Definition": {
                    "Policy": {
                        "Statement": sub(
                            f'permit(principal, action == AgentCore::Action::"{name}-{server}___{tool}", '
                            'resource == AgentCore::Gateway::"${Tools.GatewayArn}");'
                        )
                    }
                },
            },
            "Permit only this copy's read tools; app still checks per-human ownership",
            DependsOn=[
                s.title().replace("-", "") + "Target"
                for s in ("travel-discovery", "reservations", "customer-payments")
            ],
        )
    if config.paid_inference:
        r["ModelTarget"] = resource(
            "BedrockAgentCore::GatewayTarget",
            {
                "GatewayIdentifier": att("Inference", "GatewayIdentifier"),
                "Name": name + "-model",
                "TargetConfiguration": {
                    "Inference": {"Connector": {"Source": {"ConnectorId": "bedrock-mantle"}}}
                },
                "CredentialProviderConfigurations": [
                    {"CredentialProviderType": "GATEWAY_IAM_ROLE"}
                ],
            },
            "Optional paid inference; absent by default",
            DependsOn="InferencePermission",
        )
    t["Outputs"] = {
        k: {"Value": value}
        for k, value in {
            "ToolGatewayUrl": att("Tools", "GatewayUrl"),
            "InferenceGatewayUrl": att("Inference", "GatewayUrl"),
            "ToolGatewayArn": att("Tools", "GatewayArn"),
            "InferenceGatewayArn": att("Inference", "GatewayArn"),
        }.items()
    }
    return t
