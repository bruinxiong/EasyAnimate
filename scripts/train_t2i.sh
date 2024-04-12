export MODEL_NAME="models/Diffusion_Transformer/PixArt-XL-2-512x512"
export DATASET_NAME="datasets/internal_datasets/"
export DATASET_META_NAME="datasets/internal_datasets/metadata.json"

# When train model with multi machines, use "--config_file accelerate.yaml" instead of "--mixed_precision='bf16'".
# vae_mode can be choosen in "normal" and "magvit"
# transformer_mode can be choosen in "normal" and "kvcompress"
accelerate launch --mixed_precision="bf16" scripts/train_t2i.py \
  --pretrained_model_name_or_path=$MODEL_NAME \
  --train_data_dir=$DATASET_NAME \
  --train_data_meta=$DATASET_META_NAME \
  --config_path "config/easyanimate_image_normal_v1.yaml" \
  --train_data_format="normal" \
  --caption_column="text" \
  --resolution=512 \
  --train_batch_size=2 \
  --gradient_accumulation_steps=1 \
  --dataloader_num_workers=8 \
  --num_train_epochs=50 \
  --checkpointing_steps=500 \
  --validation_prompts="1girl, bangs, blue eyes, blunt bangs, blurry, blurry background, bob cut, depth of field, lips, looking at viewer, motion blur, nose, realistic, red lips, shirt, short hair, solo, white shirt." \
  --validation_epochs=1 \
  --validation_steps=100 \
  --learning_rate=1e-05 \
  --lr_scheduler="constant_with_warmup" \
  --lr_warmup_steps=50 \
  --seed=42 \
  --max_grad_norm=1 \
  --output_dir="output_dir_t2i" \
  --enable_xformers_memory_efficient_attention \
  --gradient_checkpointing \
  --mixed_precision='bf16' \
  --use_ema \
  --trainable_modules "."