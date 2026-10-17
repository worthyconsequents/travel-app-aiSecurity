{{/* ------------------------------------------------------------------ */}}
{{/* Naming + labels (standard Helm idioms) */}}
{{/* ------------------------------------------------------------------ */}}

{{- define "ai-gateway.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Resources are named after the release alone, so the gateway a customer
     installs as "gw-prod" is gw-prod-gateway — the chart name never appears. */}}
{{- define "ai-gateway.fullname" -}}
{{- default .Release.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ai-gateway.gateway.fullname" -}}
{{- printf "%s-gateway" (include "ai-gateway.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}


{{/* Device-token Secret name: an operator-supplied existingSecret, else a */}}
{{/* name override, else <gateway>-auth-token. */}}
{{- define "ai-gateway.gateway.authTokenSecretName" -}}
{{- if .Values.gateway.visionone.authToken.existingSecret -}}
{{- .Values.gateway.visionone.authToken.existingSecret -}}
{{- else -}}
{{- default (printf "%s-auth-token" (include "ai-gateway.gateway.fullname" .)) .Values.gateway.visionone.authToken.name -}}
{{- end -}}
{{- end -}}

{{/* Master-key Secret name: an operator-supplied existingSecret, else a name */}}
{{/* override, else <release>-master-key. */}}
{{- define "ai-gateway.admin.masterKeySecretName" -}}
{{- if .Values.admin.masterKey.existingSecret -}}
{{- .Values.admin.masterKey.existingSecret -}}
{{- else -}}
{{- default (printf "%s-master-key" (include "ai-gateway.fullname" .)) .Values.admin.masterKey.name -}}
{{- end -}}
{{- end -}}

{{/* Master-key mount path and the file within it the processes read. */}}
{{- define "ai-gateway.admin.masterKeyMountPath" -}}
{{- .Values.admin.masterKey.mountPath | default "/etc/secrets/ai-gateway-admin" -}}
{{- end -}}
{{- define "ai-gateway.admin.masterKeyFile" -}}
{{- printf "%s/master-key" (include "ai-gateway.admin.masterKeyMountPath" .) -}}
{{- end -}}

{{/* Responses resp_ id key: always chart-provisioned, no operator knob. */}}
{{- define "ai-gateway.gateway.respIDKeySecretName" -}}
{{- printf "%s-resp-id-key" (include "ai-gateway.gateway.fullname" .) -}}
{{- end -}}
{{- define "ai-gateway.gateway.respIDKeyMountPath" -}}
{{- "/etc/secrets/resp-id-key" -}}
{{- end -}}
{{- define "ai-gateway.gateway.respIDKeyFile" -}}
{{- printf "%s/resp-id-key" (include "ai-gateway.gateway.respIDKeyMountPath" .) -}}
{{- end -}}

{{/* Gateway keypair: X25519 private key shared by every replica so any of them
     can open the DEK sealed to the gateway public key. An operator-supplied
     existingSecret wins (GitOps); else the chart generates one. */}}
{{- define "ai-gateway.gateway.gatewayKeySecretName" -}}
{{- if .Values.gateway.gatewayKey.existingSecret -}}
{{- .Values.gateway.gatewayKey.existingSecret -}}
{{- else -}}
{{- default (printf "%s-gateway-key" (include "ai-gateway.gateway.fullname" .)) .Values.gateway.gatewayKey.name -}}
{{- end -}}
{{- end -}}
{{- define "ai-gateway.gateway.gatewayKeyMountPath" -}}
{{- "/etc/secrets/gateway-key" -}}
{{- end -}}
{{- define "ai-gateway.gateway.gatewayKeyFile" -}}
{{- printf "%s/gateway.key" (include "ai-gateway.gateway.gatewayKeyMountPath" .) -}}
{{- end -}}

{{/* File-mode gateway.secrets entries mount a single secret key into the pod.
     mountPath is the full on-disk file path (e.g. /etc/secrets/rdsec/api-key):
     the volume mounts its directory and kubelet writes the key under the
     basename below — a leaf file, never `path: .`, which the kubelet
     atomic-writer can't project onto a directory root. */}}
{{- define "ai-gateway.gateway.secretMountDir" -}}
{{- $parts := splitList "/" (trimPrefix "/" .) -}}
{{- if eq (len $parts) 1 }}{{ "/" }}{{- else }}{{ printf "/%s" (join "/" (initial $parts)) }}{{- end -}}
{{- end -}}
{{- define "ai-gateway.gateway.secretMountFile" -}}
{{- last (splitList "/" (trimPrefix "/" .)) -}}
{{- end -}}

{{- define "ai-gateway.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ai-gateway.labels" -}}
helm.sh/chart: {{ include "ai-gateway.chart" . }}
{{ include "ai-gateway.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | trunc 63 | trimSuffix "-" | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "ai-gateway.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ai-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "ai-gateway.gateway.selectorLabels" -}}
{{ include "ai-gateway.selectorLabels" . }}
app.kubernetes.io/component: gateway
{{- end -}}


{{- define "ai-gateway.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "ai-gateway.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* ------------------------------------------------------------------ */}}
{{/* Image refs */}}
{{/* ------------------------------------------------------------------ */}}

{{- define "ai-gateway.gateway.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s/%s/gateway:%s" .Values.image.registry .Values.image.repository $tag -}}
{{- end -}}

{{/* ------------------------------------------------------------------ */}}
{{/* Policy-source URL. A self-hosted server is a separate release from the */}}
{{/* ai-gateway-server chart, so its in-cluster address is threaded through */}}
{{/* gateway.config.server.url rather than derived here. */}}
{{/* ------------------------------------------------------------------ */}}

{{- define "ai-gateway.serverURL" -}}
{{- default .Values.gateway.visionone.url (dig "server" "url" "" .Values.gateway.config) -}}
{{- end -}}

{{/* ------------------------------------------------------------------ */}}
{{/* policy-server guard — the gateway needs a policy/catalog server. Fails */}}
{{/* the install when neither Vision One nor a self-hosted server URL is set, */}}
{{/* so misconfiguration surfaces at install rather than as a running-but- */}}
{{/* empty gateway. Called from gateway/configmap.yaml. */}}
{{/* ------------------------------------------------------------------ */}}

{{- define "ai-gateway.policyServerGuard" -}}
{{- if not (include "ai-gateway.serverURL" .) -}}
{{- fail "the gateway needs a policy server: set gateway.visionone.url for Vision One, or gateway.config.server.url to point at a self-hosted ai-gateway-server release." -}}
{{- end -}}
{{- end -}}

{{/* ------------------------------------------------------------------ */}}
{{/* Rendered gateway config.yaml — embeds the resolved server URL */}}
{{/* ------------------------------------------------------------------ */}}

{{- define "ai-gateway.gateway.configYAML" -}}
{{- $cfg := deepCopy .Values.gateway.config -}}
{{- $_ := set $cfg.server "url" (include "ai-gateway.serverURL" .) -}}
{{/* Vision One mode: setting gateway.visionone.url selects the Service Platform
     path envelope. The gateway derives the constant prefix from this flag in
     code — operators never hand-set the path. Self-hosted leaves it false. */}}
{{- if .Values.gateway.visionone.url -}}
{{- $_ := set $cfg.server "visionone" true -}}
{{- end -}}
{{/* Device-token auth (gateway↔Vision One) is always wired: the gateway enrolls
     via the bootstrap token, the leader rotates it into the Secret, and every
     pod reads it from the projected mount. On a self-hosted server the external
     scope is open so the token is benign, but the enrollment/rotation flow still
     runs — keeping deploys V1-ready. */}}
{{- $_ := set $cfg.server "device_token_secret" (include "ai-gateway.gateway.authTokenSecretName" .) -}}
{{- $_ := set $cfg.server "device_token_path" (printf "%s/token" .Values.gateway.visionone.authToken.mountPath) -}}
{{/* Wire the bundled Redis address unless the operator set their own. */}}
{{- if and .Values.gateway.redis.enabled (not (dig "store" "redis" "address" "" $cfg)) -}}
{{- $store := default dict $cfg.store -}}
{{- $redis := default dict $store.redis -}}
{{- $_ := set $redis "address" (printf "%s-redis:%v" (include "ai-gateway.fullname" .) .Values.gateway.redis.service.port) -}}
{{- $_ := set $store "redis" $redis -}}
{{- $_ := set $cfg "store" $store -}}
{{- end -}}
{{/* Point llm_proxy.resp_id_key at the provisioned key mount. */}}
{{- $llm := $cfg.llm_proxy | default dict -}}
{{- $_ := set $llm "resp_id_key" (dict "file" (include "ai-gateway.gateway.respIDKeyFile" .)) -}}
{{- $_ := set $cfg "llm_proxy" $llm -}}
{{/* koolaide hard-fails without a models_dir. Default it to the image's bundled
     inference-engine path (lib/ + models/) when scanning is enabled and the
     operator didn't set one, so koolaide.enabled works out of the box with the
     released image. An explicit gateway.config.koolaide.models_dir wins. */}}
{{- if and (dig "koolaide" "enabled" false $cfg) (not (dig "koolaide" "models_dir" "" $cfg)) -}}
{{- $kool := $cfg.koolaide | default dict -}}
{{- $_ := set $kool "models_dir" "/app/inference-engine" -}}
{{- $_ := set $cfg "koolaide" $kool -}}
{{- end -}}
{{/* events.wal.path: default to the already-mounted /tmp emptyDir, so a
     Helm-deployed pod gets crash/OOM-restart durability on the EventLog
     for free (survives a container restart within the pod, not a
     reschedule onto another node — that needs an explicit PVC path). An
     explicit gateway.config.events.wal.path wins; empty-string is honored
     as the operator's own choice to stay memory-tier. */}}
{{- if not (hasKey (dig "events" "wal" (dict) $cfg) "path") -}}
{{- $events := $cfg.events | default dict -}}
{{- $wal := $events.wal | default dict -}}
{{- $_ := set $wal "path" "/tmp/aigw-wal.db" -}}
{{- $_ := set $events "wal" $wal -}}
{{- $_ := set $cfg "events" $events -}}
{{- end -}}
{{- toYaml $cfg -}}
{{- end -}}

{{/* gateway shared-store guard — a multi-replica gateway must share catalog */}}
{{/* state (and VK-cache invalidation) via Redis; the in-memory store can't */}}
{{/* sync across pods, so replicas would run isolated, stale catalogs. Fail the */}}
{{/* install when replicaCount > 1 without a bundled or external Redis. */}}
{{- define "ai-gateway.gatewayRedisGuard" -}}
{{- if gt (int .Values.gateway.replicaCount) 1 -}}
{{- if and (not .Values.gateway.redis.enabled) (not (dig "store" "redis" "address" "" .Values.gateway.config)) -}}
{{- fail "gateway.replicaCount > 1 needs a shared catalog store: set gateway.redis.enabled=true to bundle Redis, or gateway.config.store.redis.address for an external one — the in-memory store can't sync across replicas." -}}
{{- end -}}
{{- end -}}
{{- end -}}

