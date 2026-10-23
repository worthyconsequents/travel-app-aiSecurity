"""Offline Kubernetes bundle; no credentials are rendered or read here."""

import json
import re

from scripts.fleet_templates import compact


def bundle(c, outputs, images):
    c.validate_provision()
    for image in images.values():
        if not re.fullmatch(
            rf"{c.account}\.dkr\.ecr\.{c.region}\.amazonaws\.com/{c.name}-(python|frontend|edge)@sha256:[0-9a-f]{{64}}",
            image,
        ):
            raise ValueError("Immutable images in this deployment's ECR repositories are required")
    if set(images) != {"python", "frontend", "edge"}:
        raise ValueError("All three image digests are required")
    ns = c.name
    items = [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": ns,
                "labels": {
                    "pod-security.kubernetes.io/enforce": "restricted",
                    "app.kubernetes.io/part-of": "boring-travel",
                },
            },
        }
    ]

    def obj(kind, name, spec, api="v1"):
        value = {
            "apiVersion": api,
            "kind": kind,
            "metadata": {"name": name, "namespace": ns},
            **spec,
        }
        items.append(value)
        return value

    config = {
        "APP_MODE": "aws-demo",
        "DEPLOYMENT_PROFILE": "trend-gateway",
        "MODEL_MODE": "mock",
        "ENABLE_PAID_INFERENCE": "false",
        "ENABLE_AWS_TREND_GATEWAY": "true",
        "ENABLE_TREND_GATEWAY": "true",
        "TREND_CAPABILITY_TRANSPORT": "reference",
        "TREND_RESPONSE_PROBE_ENABLED": "true",
        "TREND_K8S_NAMESPACE": ns,
        "TREND_MCP_URL": f"http://trendai-gateway-gateway.{ns}.svc.cluster.local:8081/",
        "TREND_VIRTUAL_KEY_FILE": "/run/trend/virtual-key",
        "TREND_TOOL_MAP_FILE": "/run/maps/tool-map.json",
        "AWS_REGION": c.region,
        "DATABASE_HOST": outputs["DatabaseHost"],
        "AWS_DEMO_EDGE_AUTH": "cognito-alb",
        "AWS_APP_HOSTNAME": c.hostname,
        "AWS_ALB_ARN": outputs.get("AlbArn", "UNBOUND"),
        "AWS_COGNITO_ISSUER": f"https://cognito-idp.{c.region}.amazonaws.com/{outputs['OperatorPoolId']}",
        "AWS_COGNITO_CLIENT_ID": outputs["OperatorClientId"],
        "MONITOR_PASSWORD_SOURCE": "env",
        "MONITOR_COOKIE_SECURE": "true",
        "SESSION_COOKIE_NAME": "boring_travel_" + ns.replace("-", "_"),
        "TEST_DEPLOYMENT_ID": ns,
        "TEST_RUNNER_ENABLED": "true",
        "TEST_RUNNER_BACKEND": "kubernetes-cronjob",
        "GATEWAY_URL": "http://gateway:8000",
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    obj("ConfigMap", "runtime", {"data": config})
    from services.contracts import TOOLS

    suffix = {
        "travel-discovery": "discovery",
        "reservations": "reservations",
        "customer-payments": "payments",
    }
    tool_map = {k: ns + "-" + suffix[v] + "__" + k for k, v in TOOLS.items()}
    obj("ConfigMap", "tool-map", {"data": {"tool-map.json": json.dumps(tool_map)}})
    obj("ServiceAccount", "app", {"automountServiceAccountToken": False})
    obj(
        "LimitRange",
        "defaults",
        {
            "spec": {
                "limits": [
                    {
                        "type": "Container",
                        "defaultRequest": {"cpu": "50m", "memory": "128Mi"},
                        "default": {"cpu": "500m", "memory": "256Mi"},
                    }
                ]
            }
        },
    )
    obj(
        "ResourceQuota",
        "lab-budget",
        {
            "spec": {
                "hard": {
                    "pods": "24",
                    "requests.cpu": "4",
                    "requests.memory": "10Gi",
                    "limits.memory": "16Gi",
                }
            }
        },
    )
    obj(
        "NetworkPolicy",
        "default-deny",
        {"spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}},
        "networking.k8s.io/v1",
    )
    # Same-copy traffic and DNS; other namespaces cannot reach business pods.
    obj(
        "NetworkPolicy",
        "same-copy",
        {
            "spec": {
                "podSelector": {},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [{"from": [{"podSelector": {}}]}],
                "egress": [
                    {"to": [{"podSelector": {}}]},
                    {
                        "to": [
                            {
                                "namespaceSelector": {
                                    "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                                }
                            }
                        ],
                        "ports": [{"protocol": x, "port": 53} for x in ("UDP", "TCP")],
                    },
                    {
                        "to": [{"ipBlock": {"cidr": "10.120.0.0/16"}}],
                        "ports": [{"protocol": "TCP", "port": 5432}],
                    },
                    {
                        "to": [
                            {
                                "ipBlock": {
                                    "cidr": "0.0.0.0/0",
                                    "except": [
                                        "10.0.0.0/8",
                                        "172.16.0.0/12",
                                        "192.168.0.0/16",
                                        "169.254.0.0/16",
                                    ],
                                }
                            }
                        ],
                        "ports": [{"protocol": "TCP", "port": 443}],
                    },
                ],
            }
        },
        "networking.k8s.io/v1",
    )
    obj(
        "NetworkPolicy",
        "public-edge",
        {
            "spec": {
                "podSelector": {"matchLabels": {"app": "edge"}},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [
                            {"ipBlock": {"cidr": "10.120.0.0/24"}},
                            {"ipBlock": {"cidr": "10.120.1.0/24"}},
                        ],
                        "ports": [{"protocol": "TCP", "port": 8080}],
                    }
                ],
            }
        },
        "networking.k8s.io/v1",
    )

    def service(name, port, node=False):
        obj(
            "Service",
            name,
            {
                "spec": {
                    "type": "NodePort" if node else "ClusterIP",
                    **({"externalTrafficPolicy": "Local"} if node else {}),
                    "selector": {"app": name},
                    "ports": [
                        {"port": port, "targetPort": port, **({"nodePort": 32080} if node else {})}
                    ],
                }
            },
        )

    def pod(name, command, port=None, secret_keys=(), image="python", mounts=True):
        env = [
            {"name": key, "valueFrom": {"secretKeyRef": {"name": "runtime", "key": key}}}
            for key in secret_keys
        ]
        container = {
            "name": name,
            "image": images[image],
            "command": command,
            "env": env,
            "envFrom": [{"configMapRef": {"name": "runtime"}}] if image == "python" else [],
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            },
            "resources": {
                "requests": {"cpu": "100m", "memory": "256Mi"},
                "limits": {"cpu": "1", "memory": "1Gi"},
            },
            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
        }
        volumes = [{"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}}]
        if mounts:
            volumes += [
                {
                    "name": "trend",
                    "secret": {"secretName": "trend-virtual-key", "defaultMode": 0o444},
                },
                {"name": "maps", "configMap": {"name": "tool-map"}},
            ]
            container["volumeMounts"] += [
                {"name": "trend", "mountPath": "/run/trend", "readOnly": True},
                {"name": "maps", "mountPath": "/run/maps", "readOnly": True},
            ]
        if port:
            container["ports"] = [{"containerPort": port}]
            container["readinessProbe"] = {
                "httpGet": {"path": "/health", "port": port},
                "initialDelaySeconds": 5,
                "periodSeconds": 5,
            }
            container["startupProbe"] = {
                "httpGet": {"path": "/health", "port": port},
                "failureThreshold": 40,
                "periodSeconds": 5,
            }
        return {
            "metadata": {"labels": {"app": name}},
            "spec": {
                "serviceAccountName": "app",
                "automountServiceAccountToken": False,
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 101 if image == "edge" else 1000,
                    "runAsGroup": 101 if image == "edge" else 1000,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [container],
                "volumes": volumes,
            },
        }

    database_keys = ("DATABASE_PASSWORD", "MCP_SIGNING_KEY")
    workloads = []
    for name in (
        "api",
        "gateway",
        "travel-discovery",
        "reservations",
        "customer-payments",
        "frontend",
        "edge",
        "mcp-bridge",
    ):
        port = (
            3000
            if name == "frontend"
            else 8080
            if name == "edge"
            else 8082
            if name == "mcp-bridge"
            else 8000
        )
        service(name, port, name == "edge")
        if name == "frontend":
            template_pod = pod(name, ["node", "server.js"], port, image="frontend", mounts=False)
        elif name in {"edge", "mcp-bridge"}:
            command = [
                "/bin/sh",
                "-ec",
                (
                    "envsubst '$MCP_SERVICE_KEY' < /app/bridge.conf.template > /tmp/routes.conf; "
                    if name == "mcp-bridge"
                    else "cp /app/edge.conf.template /tmp/routes.conf; "
                )
                + "exec nginx -c /app/nginx.conf -g 'daemon off;'",
            ]
            template_pod = pod(
                name,
                command,
                port,
                ("MCP_SERVICE_KEY",) if name == "mcp-bridge" else (),
                image="edge",
                mounts=False,
            )
        else:
            command = (
                ["python", "-m", "services.mcp_server"]
                if name in suffix
                else [
                    "uvicorn",
                    "services." + name + ":app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                    "--no-proxy-headers",
                ]
            )
            template_pod = pod(
                name,
                command,
                port,
                database_keys + (("MONITOR_PASSWORD",) if name == "api" else ()),
                mounts=name in {"api", "gateway"},
            )
            if name in suffix:
                template_pod["spec"]["containers"][0]["env"].append(
                    {"name": "SERVICE", "value": name}
                )
        workloads.append((name, template_pod))
    for name, template_pod in workloads:
        obj(
            "Deployment",
            name,
            {
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app": name}},
                    "template": template_pod,
                }
            },
            "apps/v1",
        )
    worker = pod(
        "test-worker",
        ["python", "-m", "services.test_worker", "--one-shot"],
        secret_keys=database_keys,
    )
    worker["spec"]["restartPolicy"] = "Never"
    obj(
        "CronJob",
        "test-worker",
        {
            "spec": {
                "schedule": "* * * * *",
                "concurrencyPolicy": "Forbid",
                "startingDeadlineSeconds": 90,
                "successfulJobsHistoryLimit": 1,
                "failedJobsHistoryLimit": 2,
                "jobTemplate": {
                    "spec": {
                        "activeDeadlineSeconds": 240,
                        "backoffLimit": 0,
                        "ttlSecondsAfterFinished": 300,
                        "template": worker,
                    }
                },
            }
        },
        "batch/v1",
    )
    obj(
        "Ingress",
        "website",
        {
            "metadata": {
                "name": "website",
                "namespace": ns,
                "annotations": {
                    "alb.ingress.kubernetes.io/scheme": "internet-facing",
                    "alb.ingress.kubernetes.io/target-type": "instance",
                    "alb.ingress.kubernetes.io/load-balancer-name": compact(c.name, "web"),
                    "alb.ingress.kubernetes.io/subnets": outputs["PublicSubnets"],
                    "alb.ingress.kubernetes.io/security-groups": outputs["IngressSecurityGroup"],
                    "alb.ingress.kubernetes.io/manage-backend-security-group-rules": "false",
                    "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}]',
                    "alb.ingress.kubernetes.io/certificate-arn": outputs["CertificateArn"],
                    "alb.ingress.kubernetes.io/healthcheck-path": "/health",
                    "alb.ingress.kubernetes.io/auth-type": "cognito",
                    "alb.ingress.kubernetes.io/auth-idp-cognito": json.dumps(
                        {
                            "userPoolARN": outputs["OperatorPoolArn"],
                            "userPoolClientID": outputs["OperatorClientId"],
                            "userPoolDomain": outputs["OperatorDomain"],
                        }
                    ),
                    "alb.ingress.kubernetes.io/auth-scope": "openid email",
                    "alb.ingress.kubernetes.io/auth-session-timeout": "3600",
                    "alb.ingress.kubernetes.io/tags": f"Project=boring-travel,Owner=dannytran,Deployment={ns}",
                },
            },
            "spec": {
                "ingressClassName": "alb",
                "rules": [
                    {
                        "host": c.hostname,
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {"name": "edge", "port": {"number": 8080}}
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        },
        "networking.k8s.io/v1",
    )
    return {"apiVersion": "v1", "kind": "List", "items": items}


def logging_bundle(c, image):
    if not re.fullmatch(
        r"public\.ecr\.aws/aws-observability/aws-for-fluent-bit@sha256:[0-9a-f]{64}", image
    ):
        raise ValueError("Use a resolved official Fluent Bit image digest")
    name = "boring-travel-logs"
    namespace = "kube-system"
    paths = ",".join(
        f"/var/log/containers/{app}-*_{c.name}_*.log"
        for app in (
            "api",
            "gateway",
            "travel-discovery",
            "reservations",
            "customer-payments",
            "test-worker",
        )
    )
    config = f"""[SERVICE]
    Flush 5
    Log_Level warn
    Parsers_File /etc/boring/cri.conf
[INPUT]
    Name tail
    Path {paths}
    Tag boring.application
    Parser cri
    Mem_Buf_Limit 5MB
    Skip_Long_Lines On
    DB /tmp/tail.db
[FILTER]
    Name grep
    Match boring.application
    Exclude log (?i)(authorization|bearer |gateway_capability|bootstrap|password|api_key)
[OUTPUT]
    Name cloudwatch_logs
    Match boring.application
    region {c.region}
    log_group_name {c.name}-application
    log_stream_prefix pod-
    auto_create_group false
"""
    parser = r"""[PARSER]
    Name cri
    Format regex
    Regex ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$
"""

    def meta(n):
        return {"name": n, "namespace": namespace}

    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": meta(name),
                "automountServiceAccountToken": False,
            },
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": meta(name),
                "data": {"fluent-bit.conf": config, "cri.conf": parser},
            },
            {
                "apiVersion": "apps/v1",
                "kind": "DaemonSet",
                "metadata": meta(name),
                "spec": {
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": {"app": name}},
                        "spec": {
                            "serviceAccountName": name,
                            "automountServiceAccountToken": False,
                            "containers": [
                                {
                                    "name": "collector",
                                    "image": image,
                                    "command": [
                                        "/fluent-bit/bin/fluent-bit",
                                        "-c",
                                        "/etc/boring/fluent-bit.conf",
                                    ],
                                    "securityContext": {
                                        "runAsUser": 0,
                                        "readOnlyRootFilesystem": True,
                                        "allowPrivilegeEscalation": False,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "50m", "memory": "64Mi"},
                                        "limits": {"cpu": "200m", "memory": "128Mi"},
                                    },
                                    "volumeMounts": [
                                        {"name": "logs", "mountPath": "/var/log", "readOnly": True},
                                        {
                                            "name": "config",
                                            "mountPath": "/etc/boring",
                                            "readOnly": True,
                                        },
                                        {"name": "tmp", "mountPath": "/tmp"},
                                    ],
                                }
                            ],
                            "volumes": [
                                {
                                    "name": "logs",
                                    "hostPath": {"path": "/var/log", "type": "Directory"},
                                },
                                {"name": "config", "configMap": {"name": name}},
                                {"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}},
                            ],
                        },
                    },
                },
            },
        ],
    }


def with_discovery(c, value, images):
    items = value["items"]
    runtime = next(
        i for i in items if i["kind"] == "ConfigMap" and i["metadata"]["name"] == "runtime"
    )
    runtime["data"].update(
        {
            "ENABLE_AWS_TREND_FIXTURE": "true",
            "TOOL_CHANGES_ENABLED": "true",
            "MODEL_PROBE_ENABLED": "true",
            "TOOL_CHANGE_CONTROL_KEY_FILE": "/run/probe/control-key",
            "TOOL_CHANGE_UPSTREAM_KEY_FILE": "/run/probe/upstream-key",
            "MODEL_PROBE_KEY_FILE": "/run/probe/model-key",
            "TOOL_CHANGE_MAP_FILE": "/run/maps/tool-change-map.json",
        }
    )
    prefix = c.name + "-tool-changes__"
    maps = next(
        i for i in items if i["kind"] == "ConfigMap" and i["metadata"]["name"] == "tool-map"
    )
    maps["data"]["tool-change-map.json"] = json.dumps(
        {
            "upstream_prefix": prefix,
            "tools": {
                n: prefix + n for n in ("fixture_status", "fixture_new_tool", "search_hotels")
            },
        }
    )
    policy = next(
        i for i in items if i["kind"] == "NetworkPolicy" and i["metadata"]["name"] == "same-copy"
    )
    policy["spec"]["egress"] = [
        r
        for r in policy["spec"]["egress"]
        if not any(x.get("ipBlock", {}).get("cidr") == "0.0.0.0/0" for x in r.get("to", []))
    ]

    def add(kind, name, content, api="v1"):
        items.append(
            {
                "apiVersion": api,
                "kind": kind,
                "metadata": {"name": name, "namespace": c.name},
                **content,
            }
        )

    for name, selector in [
        ("api-public-https", {"app": "api"}),
        ("gateway-public-https", {"app.kubernetes.io/instance": "trendai-gateway"}),
    ]:
        add(
            "NetworkPolicy",
            name,
            {
                "spec": {
                    "podSelector": {"matchLabels": selector},
                    "policyTypes": ["Egress"],
                    "egress": [
                        {
                            "to": [
                                {
                                    "ipBlock": {
                                        "cidr": "0.0.0.0/0",
                                        "except": [
                                            "10.0.0.0/8",
                                            "172.16.0.0/12",
                                            "192.168.0.0/16",
                                            "169.254.0.0/16",
                                        ],
                                    }
                                }
                            ],
                            "ports": [{"protocol": "TCP", "port": 443}],
                        }
                    ],
                }
            },
            "networking.k8s.io/v1",
        )
    # The vendor gateway uses Kubernetes leases and device-token Secrets. The
    # control-plane ENIs reside in these foundation-owned private subnets.
    add(
        "NetworkPolicy",
        "gateway-control-plane",
        {
            "spec": {
                "podSelector": {"matchLabels": {"app.kubernetes.io/instance": "trendai-gateway"}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [
                            {"ipBlock": {"cidr": "10.120.10.0/24"}},
                            {"ipBlock": {"cidr": "10.120.11.0/24"}},
                            # VPC CNI can evaluate the pre-DNAT service address.
                            {"ipBlock": {"cidr": "172.20.0.1/32"}},
                        ],
                        "ports": [{"protocol": "TCP", "port": 443}],
                    }
                ],
            }
        },
        "networking.k8s.io/v1",
    )
    cron = next(i for i in items if i["kind"] == "CronJob")
    worker = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    worker["volumes"].append(
        {"name": "probe", "secret": {"secretName": "discovery-fixture", "defaultMode": 0o444}}
    )
    worker["containers"][0]["volumeMounts"].append(
        {"name": "probe", "mountPath": "/run/probe", "readOnly": True}
    )
    for name, module, flag in [
        ("tool-change-fixture", "tool_change_fixture", "TOOL_CHANGES_ENABLED"),
        ("mock-model-provider", "mock_model_provider", "MODEL_PROBE_ENABLED"),
    ]:
        add(
            "Service",
            name,
            {
                "spec": {
                    "type": "ClusterIP",
                    "selector": {"app": name},
                    "ports": [{"port": 8000, "targetPort": 8000}],
                }
            },
        )
        add(
            "Deployment",
            name,
            {
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": {"app": name}},
                        "spec": {
                            "serviceAccountName": "app",
                            "automountServiceAccountToken": False,
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 1000,
                                "runAsGroup": 1000,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [
                                {
                                    "name": name,
                                    "image": images["python"],
                                    "command": [
                                        "uvicorn",
                                        "services." + module + ":create_app",
                                        "--factory",
                                        "--host",
                                        "0.0.0.0",
                                        "--port",
                                        "8000",
                                    ],
                                    "env": [
                                        {"name": k, "value": v}
                                        for k, v in {
                                            "APP_MODE": "aws-demo",
                                            "MODEL_MODE": "mock",
                                            "ENABLE_AWS_TREND_GATEWAY": "true",
                                            "ENABLE_AWS_TREND_FIXTURE": "true",
                                            "TREND_K8S_NAMESPACE": c.name,
                                            flag: "true",
                                            "TOOL_CHANGE_CONTROL_KEY_FILE": "/run/probe/control-key",
                                            "TOOL_CHANGE_UPSTREAM_KEY_FILE": "/run/probe/upstream-key",
                                            "MODEL_PROBE_KEY_FILE": "/run/probe/model-key",
                                        }.items()
                                    ],
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "100m", "memory": "128Mi"},
                                        "limits": {"cpu": "500m", "memory": "256Mi"},
                                    },
                                    "ports": [{"containerPort": 8000}],
                                    "readinessProbe": {
                                        "httpGet": {"path": "/health", "port": 8000}
                                    },
                                    "volumeMounts": [
                                        {
                                            "name": "probe",
                                            "mountPath": "/run/probe",
                                            "readOnly": True,
                                        },
                                        {"name": "tmp", "mountPath": "/tmp"},
                                    ],
                                }
                            ],
                            "volumes": [
                                {
                                    "name": "probe",
                                    "secret": {
                                        "secretName": "discovery-fixture",
                                        "defaultMode": 0o444,
                                    },
                                },
                                {"name": "tmp", "emptyDir": {"sizeLimit": "16Mi"}},
                            ],
                        },
                    },
                }
            },
            "apps/v1",
        )
    add(
        "Service",
        "model-probe-link",
        {
            "spec": {
                "type": "ExternalName",
                "externalName": f"trendai-gateway-gateway.{c.name}.svc.cluster.local",
                "ports": [{"port": 8080}],
            }
        },
    )
    return value
