#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="aegisops-cluster"

echo "Stopping local AegisOps processes and cleaning up Kind cluster..."
if kind get clusters 2>/dev/null | grep -q "$CLUSTER_NAME"; then
    kind delete cluster --name "$CLUSTER_NAME"
    echo "✔ Cluster '$CLUSTER_NAME' deleted."
fi

echo "Cleanup complete."
