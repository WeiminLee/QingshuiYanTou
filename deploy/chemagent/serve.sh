#!/bin/bash
M=/mnt/shared-storage-user/liweimin/qingshui
MODELS=$M/models; LOG=$M/serve
mkdir -p $LOG $M/cache/{triton,deepgemm,vllm,torch_ext,flashinfer}
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export MAX_JOBS=4
export TRITON_CACHE_DIR=$M/cache/triton
export DG_JIT_CACHE_DIR=$M/cache/deepgemm
export DG_CACHE_DIR=$M/cache/deepgemm
export VLLM_CACHE_ROOT=$M/cache/vllm
export TORCH_EXTENSIONS_DIR=$M/cache/torch_ext
export FLASHINFER_CACHE_DIR=$M/cache/flashinfer
IP=$(hostname -i | awk '{print $1}')
VLLM=/usr/local/bin/vllm
echo "[serve] node_ip=$IP $(date -Is) vllm=$($VLLM --version 2>&1 | tail -1)" | tee $LOG/serve.log

CUDA_VISIBLE_DEVICES=0 "$VLLM" serve "$MODELS/bge-m3" \
  --served-model-name bge-m3 --host 0.0.0.0 --port 23456 \
  --gpu-memory-utilization 0.03 --max-model-len 8192 > $LOG/embed.log 2>&1 &
EMB=$!
CUDA_VISIBLE_DEVICES=0 "$VLLM" serve "$MODELS/Qwen3.6-35B-A3B-FP8" \
  --served-model-name Qwen3.6-35B-A3B --host 0.0.0.0 --port 23457 \
  --tensor-parallel-size 1 --max-model-len 32768 --gpu-memory-utilization 0.62 \
  --trust-remote-code --language-model-only > $LOG/llm.log 2>&1 &
LLM=$!

for i in $(seq 1 240); do
  e=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:23456/v1/models)
  l=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:23457/v1/models)
  echo "[serve] t=${i} embed=$e llm=$l" >> $LOG/serve.log
  [ "$e" = "200" ] && [ "$l" = "200" ] && break
  kill -0 $LLM 2>/dev/null || echo "[serve] WARN llm exited" >> $LOG/serve.log
  sleep 10
done
cat > $M/endpoints.json <<JSON
{"node_ip":"$IP","embedding":"http://$IP:23456/v1","llm":"http://$IP:23457/v1","embedding_model":"bge-m3","llm_model":"Qwen3.6-35B-A3B","updated_at":"$(date -Is)"}
JSON
echo "[serve] endpoints:"; cat $M/endpoints.json
wait $EMB $LLM
