#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="aegisops-cluster"

echo "================================================================"
echo "🚀 Bootstrapping AegisOps Local Kubernetes Environment"
echo "================================================================"

if kind get clusters | grep -q "$CLUSTER_NAME"; then
    echo "✔ Kind cluster '$CLUSTER_NAME' already exists."
else
    echo "Creating Kind cluster '$CLUSTER_NAME'..."
    kind create cluster --name "$CLUSTER_NAME"
fi

kubectl cluster-info --context "kind-$CLUSTER_NAME"

echo "1. Applying Namespaces..."
kubectl apply -f k8s/base/namespace.yaml

echo "2. Applying AegisOps Custom Resource Definitions (CRDs)..."
kubectl apply -f k8s/crds/

echo "3. Applying RBAC ServiceAccounts and ClusterRoles..."
kubectl apply -f k8s/base/rbac.yaml

echo "4. Deploying Demo Microservices Suite (payment-service, order-service)..."
kubectl apply -f k8s/demo-apps/

echo "5. Verifying deployed resources in namespace 'production'..."
kubectl get pods -n production

echo "================================================================"
echo "✅ AegisOps Cluster Infrastructure Ready!"
echo "================================================================"
