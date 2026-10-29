"""Convert Real-ESRGAN x4plus_anime_6B (RRDBNet, 6 blocks) weights to ONNX for upscale.py.

Needs PyTorch and onnx in a separate, throwaway environment (the app itself only needs
onnxruntime):

    python3.12 -m venv /tmp/conv && /tmp/conv/bin/pip install "torch==2.2.2" "numpy<2" onnx
    curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth
    /tmp/conv/bin/python tools/esrgan_to_onnx.py RealESRGAN_x4plus_anime_6B.pth models/realesrgan_anime6b_x4.onnx

The weights load with weights_only=True and must match this architecture exactly (strict).
SHA-256 of the .pth used: f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da
"""
import sys
import torch
from torch import nn
from torch.nn import functional as F


class RDB(nn.Module):
    def __init__(self, nf=64, gc=32):
        super().__init__()
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, nf=64, gc=32):
        super().__init__()
        self.rdb1, self.rdb2, self.rdb3 = RDB(nf, gc), RDB(nf, gc), RDB(nf, gc)

    def forward(self, x):
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    def __init__(self, nb=6, nf=64, gc=32):
        super().__init__()
        self.conv_first = nn.Conv2d(3, nf, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(nf, gc) for _ in range(nb)])
        self.conv_body = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_hr = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_last = nn.Conv2d(nf, 3, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, True)

    def forward(self, x):
        feat = self.conv_first(x)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


src, dst = sys.argv[1], sys.argv[2]
sd = torch.load(src, map_location="cpu", weights_only=True)
sd = sd.get("params_ema", sd.get("params", sd))
net = RRDBNet()
missing, unexpected = net.load_state_dict(sd, strict=True), None
net.eval()
x = torch.rand(1, 3, 32, 32)
with torch.no_grad():
    y = net(x)
print("ok, test output", tuple(y.shape))
torch.onnx.export(net, x, dst, input_names=["input"], output_names=["output"], opset_version=17,
                  dynamic_axes={"input": {2: "h", 3: "w"}, "output": {2: "h4", 3: "w4"}})
print("written", dst)
