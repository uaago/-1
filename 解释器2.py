import sys
import torch

print("Python 路径", sys.executable)
print("CUDA 可用", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU 型号", torch.cuda.get_device_name(0))

