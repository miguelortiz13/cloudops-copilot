# Agente de Kubernetes

Agente de solo lectura que envía cada 5 minutos una foto del clúster a CloudOps Copilot. Funciona en AKS, EKS o fuera de la nube.

```bash
kubectl create namespace cloudops
kubectl -n cloudops create secret generic cloudops-agent \
  --from-literal=cluster-name=<nombre> --from-literal=upload-url="<terraform output kubernetes_agent_upload_urls>"
kubectl apply -k k8s-agent/
```

Guía completa, permisos y qué datos viajan: [docs/modules/kubernetes-sre.md](../docs/modules/kubernetes-sre.md).
