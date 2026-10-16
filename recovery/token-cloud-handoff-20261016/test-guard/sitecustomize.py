"""离线测试保护：拒绝真实网络连接和容器启动；子Python进程同样生效。"""
import sys

def offline_guard(event,args):
    # 测试可使用MockTransport，但不能连接任何实际模型或网络服务。
    if event in {'socket.connect','socket.getaddrinfo'}:
        raise RuntimeError('offline_validation_network_denied')
    if event=='subprocess.Popen':
        command=args[1]
        executable=command[0] if isinstance(command,(tuple,list)) else str(command).split()[0]
        if str(executable).rsplit('/',1)[-1] in {'docker','podman','nerdctl'}:
            raise RuntimeError('offline_validation_container_denied')
sys.addaudithook(offline_guard)
