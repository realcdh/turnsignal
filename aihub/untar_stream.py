"""AI Hub 다운로드(tar 안에 분할 zip part0,1,...)를 표준입력으로 받아 zip 바이트만 이어서 표준출력으로 흘림"""
import sys, tarfile, time
out, n, t0 = sys.stdout.buffer, 0, time.time()
tf = tarfile.open(fileobj=sys.stdin.buffer, mode='r|')
for m in tf:
    if not m.isfile():
        continue
    sys.stderr.write(f'member {m.name} {m.size/1e9:.2f}GB\n'); sys.stderr.flush()
    f = tf.extractfile(m)
    while True:
        b = f.read(1 << 22)
        if not b:
            break
        out.write(b); n += len(b)
        if n // (1 << 30) != (n - len(b)) // (1 << 30):
            sys.stderr.write(f'{n/1e9:.1f}GB {n/1e6/(time.time()-t0):.1f}MB/s\n'); sys.stderr.flush()
