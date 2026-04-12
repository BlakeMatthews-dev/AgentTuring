{{/*
Stronghold Helm helper templates.

Naming follows upstream Helm conventions (see the Bitnami Common chart
library and the Kubernetes Helm best practices guide). All workload
templates in PR-7..PR-12 must use these helpers; no template should emit
a bare name or an ad-hoc label block.
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "stronghold.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.

We truncate at 63 characters because some Kubernetes name fields are
limited to this by the DNS (RFC 1123) label limit. If release name contains
chart name it will be used as a full name.
*/}}
{{- define "stronghold.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Chart label (name-version).
*/}}
{{- define "stronghold.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels applied to every rendered resource's metadata.labels.

Includes the stronghold.io/priority-tier placeholder which individual
workload templates in PR-7..PR-12 will override with the component's
actual tier (P0..P5) via `merge`.
*/}}
{{- define "stronghold.labels" -}}
helm.sh/chart: {{ include "stronghold.chart" . }}
{{ include "stronghold.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: stronghold
stronghold.io/priority-tier: none
{{- end -}}

{{/*
Selector labels — the subset of common labels that are used in pod
selectors and must therefore remain immutable across chart upgrades.
*/}}
{{- define "stronghold.selectorLabels" -}}
app.kubernetes.io/name: {{ include "stronghold.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Resolve the namespace for a resource. Falls back to the release namespace
when .Values.namespace.name is unset, per ADR-K8S-001 §"Consequences".
*/}}
{{- define "stronghold.namespace" -}}
{{- default .Release.Namespace .Values.namespace.name -}}
{{- end -}}

{{/*
Compose an image reference from registry + repository + tag.

Usage:
  {{ include "stronghold.image" (dict "image" .Values.image "root" .) }}

Falls back to the chart appVersion for the tag when none is provided,
matching the upstream Kubernetes image versioning guidance.
*/}}
{{- define "stronghold.image" -}}
{{- $image := .image -}}
{{- $root := .root -}}
{{- $registry := default "" $image.registry -}}
{{- $repository := $image.repository -}}
{{- $tag := default $root.Chart.AppVersion $image.tag -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end -}}

{{/*
Image pull policy. Defaults to IfNotPresent for pinned tags and Always
for the floating "latest" tag, per the Kubernetes images documentation.
*/}}
{{- define "stronghold.imagePullPolicy" -}}
{{- $image := .image -}}
{{- $tag := default "latest" $image.tag -}}
{{- if $image.pullPolicy -}}
{{- $image.pullPolicy -}}
{{- else if eq $tag "latest" -}}
Always
{{- else -}}
IfNotPresent
{{- end -}}
{{- end -}}

{{/*
Boolean helper for OpenShift gating. Returns "true" or "" (empty string)
so it can be used with `{{- if (include "stronghold.openshiftEnabled" .) }}`.
*/}}
{{- define "stronghold.openshiftEnabled" -}}
{{- if and .Values.openshift .Values.openshift.enabled -}}
true
{{- end -}}
{{- end -}}

{{/*
Prefixed PriorityClass name for a given tier (P0..P5).

Usage:
  priorityClassName: {{ include "stronghold.priorityClassName" (dict "tier" "P0" "root" .) }}
*/}}
{{- define "stronghold.priorityClassName" -}}
{{- $tier := .tier | lower -}}
{{- printf "stronghold-%s" $tier -}}
{{- end -}}

{{/*
Per-component ServiceAccount name helpers. Each returns the
fullname-prefixed SA name so two releases in the same namespace do not
collide on SA names.
*/}}
{{- define "stronghold.serviceAccountName.strongholdApi" -}}
{{- printf "%s-%s" (include "stronghold.fullname" .) .Values.serviceAccounts.strongholdApi.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "stronghold.serviceAccountName.mcpDeployer" -}}
{{- printf "%s-%s" (include "stronghold.fullname" .) .Values.serviceAccounts.mcpDeployer.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "stronghold.serviceAccountName.postgres" -}}
{{- printf "%s-%s" (include "stronghold.fullname" .) .Values.serviceAccounts.postgres.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "stronghold.serviceAccountName.litellm" -}}
{{- printf "%s-%s" (include "stronghold.fullname" .) .Values.serviceAccounts.litellm.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "stronghold.serviceAccountName.phoenix" -}}
{{- printf "%s-%s" (include "stronghold.fullname" .) .Values.serviceAccounts.phoenix.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
