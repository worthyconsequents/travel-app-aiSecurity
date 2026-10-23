"""Isolated EKS/RDS foundation. No AgentCore resources or tenant credentials."""

from scripts.fleet_templates import att, policy, ref, resource, sub, template


def foundation(c):
    c.validate_provision()
    t = template("Isolated boring-travel Trend gateway AWS test foundation; no paid inference.")
    t["Metadata"]["com.aws.cloudformation.Context"] = {
        "ref": [{"at": "infra/trend-aws/README.md", "has": "scope, costs and acceptance gates"}],
        "must": [
            "Do not modify existing clusters, DNS applications or AgentCore deployments",
            "All application AWS names start dannytran-boring-travel; one test copy only",
        ],
    }
    r = t["Resources"]
    tags = [
        {"Key": "Project", "Value": "boring-travel"},
        {"Key": "Deployment", "Value": c.name},
        {"Key": "Owner", "Value": "dannytran"},
    ]

    def add(key, kind, props, why, **extra):
        r[key] = resource(kind, props, why, ["Dedicated to this test deployment"], **extra)

    add(
        "Vpc",
        "EC2::VPC",
        {
            "CidrBlock": "10.120.0.0/16",
            "EnableDnsSupport": True,
            "EnableDnsHostnames": True,
            "Tags": tags + [{"Key": "Name", "Value": c.name}],
        },
        "Dedicated networking; no changes to existing VPCs",
    )
    add("InternetGateway", "EC2::InternetGateway", {"Tags": tags}, "Public ALB and NAT routing")
    add(
        "GatewayAttachment",
        "EC2::VPCGatewayAttachment",
        {"VpcId": ref("Vpc"), "InternetGatewayId": ref("InternetGateway")},
        "Bind only this VPC",
    )
    add(
        "PublicRoutes",
        "EC2::RouteTable",
        {"VpcId": ref("Vpc"), "Tags": tags},
        "ALB/NAT public subnets",
    )
    add(
        "InternetRoute",
        "EC2::Route",
        {
            "RouteTableId": ref("PublicRoutes"),
            "DestinationCidrBlock": "0.0.0.0/0",
            "GatewayId": ref("InternetGateway"),
        },
        "Outbound and load balancer routing",
        DependsOn="GatewayAttachment",
    )
    azs = {"Fn::GetAZs": ""}
    for i in (0, 1):
        for public in (True, False):
            key = ("Public" if public else "Private") + str(i)
            cidr = f"10.120.{i if public else 10 + i}.0/24"
            add(
                key,
                "EC2::Subnet",
                {
                    "VpcId": ref("Vpc"),
                    "CidrBlock": cidr,
                    "AvailabilityZone": {"Fn::Select": [i, azs]},
                    "MapPublicIpOnLaunch": False,
                    "Tags": tags
                    + [
                        {
                            "Key": "kubernetes.io/role/" + ("elb" if public else "internal-elb"),
                            "Value": "1",
                        }
                    ],
                },
                "Private compute and separate public ingress across two AZs",
            )
            if public:
                add(
                    key + "Route",
                    "EC2::SubnetRouteTableAssociation",
                    {"SubnetId": ref(key), "RouteTableId": ref("PublicRoutes")},
                    "Attach public routes",
                )
    add("NatAddress", "EC2::EIP", {"Domain": "vpc", "Tags": tags}, "Dedicated billed NAT IPv4")
    add(
        "Nat",
        "EC2::NatGateway",
        {
            "SubnetId": ref("Public0"),
            "AllocationId": att("NatAddress", "AllocationId"),
            "Tags": tags,
        },
        "One NAT for a cost-bounded lab, not a high availability production design",
        DependsOn="GatewayAttachment",
    )
    add(
        "PrivateRoutes",
        "EC2::RouteTable",
        {"VpcId": ref("Vpc"), "Tags": tags},
        "Private node egress",
    )
    add(
        "NatRoute",
        "EC2::Route",
        {
            "RouteTableId": ref("PrivateRoutes"),
            "DestinationCidrBlock": "0.0.0.0/0",
            "NatGatewayId": ref("Nat"),
        },
        "Pull images and report to Vision One",
    )
    for i in (0, 1):
        add(
            "PrivateRoute" + str(i),
            "EC2::SubnetRouteTableAssociation",
            {"SubnetId": ref("Private" + str(i)), "RouteTableId": ref("PrivateRoutes")},
            "Nodes have no public addresses",
        )
    add(
        "IngressSecurity",
        "EC2::SecurityGroup",
        {
            "GroupDescription": "Operator HTTPS only",
            "VpcId": ref("Vpc"),
            "SecurityGroupIngress": [
                {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": c.operator_cidr}
            ],
            "Tags": tags,
        },
        "Only operator network may reach the authenticated ALB",
    )
    add(
        "DatabaseSecurity",
        "EC2::SecurityGroup",
        {"GroupDescription": "Private PostgreSQL", "VpcId": ref("Vpc"), "Tags": tags},
        "No public or VPC-wide database ingress",
    )
    for key, principal, managed in [
        ("ClusterRole", "eks.amazonaws.com", ["AmazonEKSClusterPolicy"]),
        (
            "NodeRole",
            "ec2.amazonaws.com",
            [
                "AmazonEKSWorkerNodePolicy",
                "AmazonEC2ContainerRegistryPullOnly",
                "AmazonEKS_CNI_Policy",
            ],
        ),
    ]:
        add(
            key,
            "IAM::Role",
            {
                "RoleName": c.name + "-" + key.lower(),
                "AssumeRolePolicyDocument": policy(
                    [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": principal},
                            "Action": "sts:AssumeRole",
                        }
                    ]
                ),
                "ManagedPolicyArns": [
                    sub("arn:${AWS::Partition}:iam::aws:policy/" + v) for v in managed
                ],
                "Tags": tags,
            },
            "Service execution role; no application data or model permissions",
        )
    add(
        "ClusterLogs",
        "Logs::LogGroup",
        {"LogGroupName": "/aws/eks/" + c.name + "/cluster", "RetentionInDays": 7, "Tags": tags},
        "Bounded control-plane audit history",
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    add(
        "Cluster",
        "EKS::Cluster",
        {
            "Name": c.name,
            "Version": c.eks_version,
            "RoleArn": att("ClusterRole"),
            "AccessConfig": {
                "AuthenticationMode": "API",
                "BootstrapClusterCreatorAdminPermissions": False,
            },
            "ResourcesVpcConfig": {
                "SubnetIds": [ref("Private0"), ref("Private1")],
                "EndpointPrivateAccess": True,
                "EndpointPublicAccess": True,
                "PublicAccessCidrs": [c.operator_cidr],
            },
            "Logging": {
                "ClusterLogging": {
                    "EnabledTypes": [
                        {"Type": x}
                        for x in ("api", "audit", "authenticator", "controllerManager", "scheduler")
                    ]
                }
            },
            "Tags": tags,
        },
        "Dedicated Kubernetes control plane; admin endpoint limited to operator CIDR",
        DependsOn="ClusterLogs",
    )
    add(
        "OperatorAccess",
        "EKS::AccessEntry",
        {
            "ClusterName": ref("Cluster"),
            "PrincipalArn": c.operator_arn,
            "Type": "STANDARD",
            "AccessPolicies": [
                {
                    "PolicyArn": sub(
                        "arn:${AWS::Partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
                    ),
                    "AccessScope": {"Type": "cluster"},
                }
            ],
            "Tags": tags,
        },
        "Explicit deployer access to this new cluster only",
    )
    add(
        "NodeLaunch",
        "EC2::LaunchTemplate",
        {
            "LaunchTemplateName": c.name + "-nodes",
            "LaunchTemplateData": {
                "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeSize": 30,
                            "VolumeType": "gp3",
                            "Encrypted": True,
                            "DeleteOnTermination": True,
                        },
                    }
                ],
                "TagSpecifications": [
                    {
                        "ResourceType": "instance",
                        "Tags": tags + [{"Key": "Name", "Value": c.name + "-node"}],
                    }
                ],
            },
        },
        "Encrypted disks and IMDSv2; pods cannot fall back to node credentials",
    )
    add(
        "Nodes",
        "EKS::Nodegroup",
        {
            "ClusterName": ref("Cluster"),
            "NodegroupName": c.name + "-nodes",
            "NodeRole": att("NodeRole"),
            "Subnets": [ref("Private0"), ref("Private1")],
            "InstanceTypes": ["t3.large"],
            "AmiType": "AL2023_x86_64_STANDARD",
            "CapacityType": "ON_DEMAND",
            "ScalingConfig": {"MinSize": 2, "DesiredSize": 2, "MaxSize": 2},
            "LaunchTemplate": {
                "Id": ref("NodeLaunch"),
                "Version": att("NodeLaunch", "LatestVersionNumber"),
            },
            "Tags": {x["Key"]: x["Value"] for x in tags},
        },
        "Two fixed lab nodes; no autoscaling above the cost-reviewed capacity",
        DependsOn="NatRoute",
    )
    add(
        "DatabaseIngress",
        "EC2::SecurityGroupIngress",
        {
            "GroupId": ref("DatabaseSecurity"),
            "IpProtocol": "tcp",
            "FromPort": 5432,
            "ToPort": 5432,
            "SourceSecurityGroupId": att("Cluster", "ClusterSecurityGroupId"),
        },
        "Only this cluster can connect to PostgreSQL",
    )
    add(
        "NodeIngress",
        "EC2::SecurityGroupIngress",
        {
            "GroupId": att("Cluster", "ClusterSecurityGroupId"),
            "IpProtocol": "tcp",
            "FromPort": 32080,
            "ToPort": 32080,
            "SourceSecurityGroupId": ref("IngressSecurity"),
        },
        "Only the authenticated ALB reaches the app NodePort",
    )
    for key in ("Signing", "Monitor", "Upstream", "DatabasePassword"):
        add(
            key + "Secret",
            "SecretsManager::Secret",
            {
                "Name": c.name + "-" + key.lower(),
                "GenerateSecretString": {
                    "SecretStringTemplate": "{}",
                    "GenerateStringKey": "password",
                    "PasswordLength": 48,
                    "ExcludePunctuation": True,
                },
                "Tags": tags,
            },
            "Isolated generated secret; never embedded in templates or outputs",
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
    add(
        "DatabaseSubnets",
        "RDS::DBSubnetGroup",
        {
            "DBSubnetGroupName": c.name + "-db",
            "DBSubnetGroupDescription": "Private boring-travel database",
            "SubnetIds": [ref("Private0"), ref("Private1")],
            "Tags": tags,
        },
        "Private database addresses",
    )
    add(
        "Database",
        "RDS::DBInstance",
        {
            "DBInstanceIdentifier": c.name + "-db",
            "Engine": "postgres",
            "EngineVersion": "17.11",
            "DBInstanceClass": "db.t4g.micro",
            "AllocatedStorage": "20",
            "StorageType": "gp3",
            "StorageEncrypted": True,
            "DBName": "travel_demo",
            "MasterUsername": "travel_demo",
            "MasterUserPassword": sub(
                "{{resolve:secretsmanager:${DatabasePasswordSecret}:SecretString:password}}"
            ),
            "DBSubnetGroupName": ref("DatabaseSubnets"),
            "VPCSecurityGroups": [ref("DatabaseSecurity")],
            "PubliclyAccessible": False,
            "MultiAZ": False,
            "BackupRetentionPeriod": 1,
            "AutoMinorVersionUpgrade": True,
            "DeletionProtection": False,
            "Tags": tags,
        },
        "Small synthetic lab database; retain rather than erase on stack deletion",
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    add(
        "Certificate",
        "CertificateManager::Certificate",
        {
            "DomainName": c.hostname,
            "ValidationMethod": "DNS",
            "DomainValidationOptions": [{"DomainName": c.hostname, "HostedZoneId": c.zone}],
            "Tags": tags,
        },
        "New certificate for only the approved hostname",
    )
    add(
        "OperatorPool",
        "Cognito::UserPool",
        {
            "UserPoolName": c.name + "-operators",
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
            "UsernameAttributes": ["email"],
            "AutoVerifiedAttributes": ["email"],
            "Policies": {
                "PasswordPolicy": {
                    "MinimumLength": 14,
                    "RequireLowercase": True,
                    "RequireUppercase": True,
                    "RequireNumbers": True,
                    "RequireSymbols": True,
                }
            },
            "UserPoolTags": {x["Key"]: x["Value"] for x in tags},
        },
        "Dedicated invited operators; no public signup",
    )
    add(
        "OperatorClient",
        "Cognito::UserPoolClient",
        {
            "UserPoolId": ref("OperatorPool"),
            "ClientName": c.name + "-alb",
            "GenerateSecret": True,
            "AllowedOAuthFlowsUserPoolClient": True,
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": ["openid", "email"],
            "SupportedIdentityProviders": ["COGNITO"],
            "CallbackURLs": ["https://" + c.hostname + "/oauth2/idpresponse"],
            "LogoutURLs": ["https://" + c.hostname + "/"],
            "PreventUserExistenceErrors": "ENABLED",
            "EnableTokenRevocation": True,
        },
        "Confidential ALB OAuth client; no secret sent to browser",
    )
    add(
        "OperatorDomain",
        "Cognito::UserPoolDomain",
        {"Domain": c.name + "-" + c.account[-6:], "UserPoolId": ref("OperatorPool")},
        "Hosted operator login",
    )
    for component in ("python", "frontend", "edge"):
        add(
            component.title() + "Repository",
            "ECR::Repository",
            {
                "RepositoryName": c.name + "-" + component,
                "ImageTagMutability": "IMMUTABLE",
                "ImageScanningConfiguration": {"ScanOnPush": True},
                "Tags": tags,
            },
            "Sanitized app images deployed by immutable digest",
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
    r["Database"]["Metadata"]["cfn-lint"] = {"config": {"ignore_checks": ["E3691"]}}
    r["Database"]["Metadata"]["com.aws.cloudformation.Context"]["must"].append(
        "Check 17.11 availability before creation; cfn-lint 1.40 has stale version enums"
    )
    add(
        "PodIdentityAgent",
        "EKS::Addon",
        {"ClusterName": ref("Cluster"), "AddonName": "eks-pod-identity-agent"},
        "Short-lived controller credentials; no node credential access from business pods",
        DependsOn="Nodes",
    )
    add(
        "NetworkPolicyAddon",
        "EKS::Addon",
        {
            "ClusterName": ref("Cluster"),
            "AddonName": "vpc-cni",
            "ResolveConflicts": "OVERWRITE",
            "ConfigurationValues": '{"enableNetworkPolicy":"true"}',
        },
        "Enforce namespace network policies rather than treating YAML alone as protection",
        DependsOn="Nodes",
    )
    outputs = {
        "ClusterName": ref("Cluster"),
        "VpcId": ref("Vpc"),
        "PublicSubnets": {"Fn::Join": [",", [ref("Public0"), ref("Public1")]]},
        "DatabaseHost": att("Database", "Endpoint.Address"),
        "IngressSecurityGroup": ref("IngressSecurity"),
        "CertificateArn": ref("Certificate"),
        "OperatorPoolArn": att("OperatorPool"),
        "OperatorPoolId": ref("OperatorPool"),
        "OperatorClientId": ref("OperatorClient"),
        "OperatorDomain": ref("OperatorDomain"),
    }
    for key in ("Signing", "Monitor", "Upstream", "DatabasePassword"):
        outputs[key + "SecretArn"] = ref(key + "Secret")
    for component in ("python", "frontend", "edge"):
        outputs[component.title() + "Repository"] = att(
            component.title() + "Repository", "RepositoryUri"
        )
    t["Outputs"] = {
        key: {"Value": value, "Description": "Deployment reference; never a secret value"}
        for key, value in outputs.items()
    }
    return t


def addons(c):
    import json
    from pathlib import Path

    t = template("Dedicated boring-travel cluster controller and application log permissions.")
    r = t["Resources"]
    controller_policy = json.loads(
        Path("infra/trend-aws/load-balancer-controller-policy.json").read_text()
    )

    def trust_for(service_account):
        return policy(
            [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "pods.eks.amazonaws.com"},
                    "Action": ["sts:AssumeRole", "sts:TagSession"],
                    "Condition": {
                        "StringEquals": {
                            "aws:RequestTag/eks-cluster-name": c.name,
                            "aws:RequestTag/kubernetes-namespace": "kube-system",
                            "aws:RequestTag/kubernetes-service-account": service_account,
                        }
                    },
                }
            ]
        )

    r["LoadBalancerRole"] = resource(
        "IAM::Role",
        {
            "RoleName": c.name + "-alb-controller",
            "AssumeRolePolicyDocument": trust_for("aws-load-balancer-controller"),
            "Policies": [
                {"PolicyName": "OfficialControllerPolicy", "PolicyDocument": controller_policy}
            ],
        },
        "Official v2.14.1 controller policy; conditions retain controller-owned resource tagging",
        ["Trust only this cluster's kube-system controller service account"],
    )
    r["ControllerIdentity"] = resource(
        "EKS::PodIdentityAssociation",
        {
            "ClusterName": c.name,
            "Namespace": "kube-system",
            "ServiceAccount": "aws-load-balancer-controller",
            "RoleArn": att("LoadBalancerRole"),
        },
        "Short-lived controller role without exposing EC2 node credentials",
    )
    r["ApplicationLogs"] = resource(
        "Logs::LogGroup",
        {"LogGroupName": c.name + "-application", "RetentionInDays": 7},
        "Application container logs, separately correlated with Vision One events",
        ["Never log secret values or raw request capabilities"],
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    r["LogRole"] = resource(
        "IAM::Role",
        {
            "RoleName": c.name + "-logs",
            "AssumeRolePolicyDocument": trust_for("boring-travel-logs"),
            "Policies": [
                {
                    "PolicyName": "ExactLogGroup",
                    "PolicyDocument": policy(
                        [
                            {
                                "Effect": "Allow",
                                "Action": [
                                    "logs:CreateLogStream",
                                    "logs:PutLogEvents",
                                    "logs:DescribeLogStreams",
                                ],
                                "Resource": sub(
                                    "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:"
                                    + c.name
                                    + "-application:*"
                                ),
                            }
                        ]
                    ),
                }
            ],
        },
        "Log exporter can write only this lab's log group, not read application secrets",
    )
    r["LogIdentity"] = resource(
        "EKS::PodIdentityAssociation",
        {
            "ClusterName": c.name,
            "Namespace": "kube-system",
            "ServiceAccount": "boring-travel-logs",
            "RoleArn": att("LogRole"),
        },
        "Short-lived credentials only for the dedicated log exporter",
    )
    t["Outputs"] = {"ApplicationLogGroup": {"Value": ref("ApplicationLogs")}}
    return t
