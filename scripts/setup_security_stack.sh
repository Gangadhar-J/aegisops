#!/usr/bin/env bash
set -euo pipefail

echo "================================================================"
echo "🔒 Installing AegisOps Security Stack: Kyverno & Falco"
echo "================================================================"

# 1. Install Kyverno
echo "1. Adding Kyverno Helm Repository..."
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update kyverno

echo "Installing Kyverno Policy Engine..."
helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  -f k8s/security/helm-kyverno-values.yaml

echo "Applying AegisOps Guardrail ClusterPolicies..."
kubectl apply -f k8s/security/kyverno-policies.yaml

# 2. Install Falco
echo "2. Adding Falcosecurity Helm Repository..."
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm repo update falcosecurity

echo "Installing Falco Runtime Threat Detection Engine..."
helm upgrade --install falco falcosecurity/falco \
  --namespace falco \
  --create-namespace \
  -f k8s/security/helm-falco-values.yaml

echo "================================================================"
echo "✅ Kyverno and Falco Security Stack successfully deployed!"
echo "================================================================"
