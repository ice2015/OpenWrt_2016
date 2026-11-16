"""CI-only packet test in an isolated network namespace; never installed in firmware.

Run by the explicit native unittest gate via sudo unshare --net. Input files are
actual controller-generated guards. No WireGuard cryptography/hardware is faked
as a success claim: this test proves Linux filtering of established TCP flows.
"""
import pathlib
import signal
import subprocess
import sys
import uuid

ECHO = r'''
import socket,threading
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('0.0.0.0',int(__import__('sys').argv[1]))); s.listen()
def serve(c):
    with c:
        while True:
            data=c.recv(4096)
            if not data: return
            c.sendall(data)
print('READY',flush=True)
while True:
    c,_=s.accept(); threading.Thread(target=serve,args=(c,),daemon=True).start()
'''
CLIENT = r'''
import socket,sys
s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=1)
print('READY',flush=True)
for line in sys.stdin:
    try:
        s.sendall(line.encode()); data=s.recv(4096).decode().strip()
        print(data,flush=True)
    except socket.timeout: print('BLOCKED',flush=True)
'''


def main():
    root=pathlib.Path(sys.argv[1])
    tag='lite-'+uuid.uuid4().hex[:10]
    peers=[tag+'-pc',tag+'-plc']
    created=[]; children=[]
    def run(*args,**kwargs):
        res = subprocess.run(args,capture_output=True,text=True,**kwargs)
        if res.returncode != 0:
            sys.stderr.write(f"FAILED: {args}\nOUT: {res.stdout}\nERR: {res.stderr}\nINPUT:\n{kwargs.get('input','')}\n")
            raise subprocess.CalledProcessError(res.returncode,args,res.stdout,res.stderr)
        return res
    def spawn(namespace,code,*args):
        command=['ip','netns','exec',namespace] if namespace else []
        proc=subprocess.Popen([*command,sys.executable,'-u','-c',code,*map(str,args)],
                              stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        children.append(proc)
        assert proc.stdout.readline().strip()=='READY','isolated test endpoint failed to start'
        return proc
    def exchange(client,message,expected):
        client.stdin.write(message+'\n'); client.stdin.flush()
        actual=client.stdout.readline().strip()
        assert actual==expected,{'message':message,'expected':expected,'actual':actual}
    def policy(state):
        incoming='' if state=='unprotected' else (root/('native-'+state+'-input.nft')).read_text()
        forwarding='' if state=='unprotected' else (root/('native-'+state+'-forward.nft')).read_text()
        late_input='' if state=='unprotected' else 'iifname "wg_direct" tcp dport 443 accept'
        late_forward='' if state=='unprotected' else 'iifname "wg_direct" ip daddr 192.168.10.0/24 tcp accept'
        # Broad late accepts intentionally exercise the guard in front of
        # established/related handling. Reloading the table does NOT flush CT.
        rules='''table inet remote_guard_test {
chain input { type filter hook input priority filter; policy drop;
iifname "lo" accept
'''+incoming+'''
ct state { established, related } accept
'''+late_input+'''
}
chain forward { type filter hook forward priority filter; policy drop;
'''+forwarding+'''
ct state { established, related } accept
'''+late_forward+'''
}
chain output { type filter hook output priority filter; policy accept; }
chain postrouting { type nat hook postrouting priority srcnat; policy accept;
oifname "plant" ip saddr 10.77.0.10 ip daddr 192.168.10.0/24 snat to 192.168.10.254
}
}
'''
        if state!='on': rules='flush table inet remote_guard_test\n'+rules
        run('nft','--check','--file','-',input=rules)
        run('nft','--file','-',input=rules)
    def interrupted(signum,frame):
        raise TimeoutError('native packet test interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    try:
        run('ip','link','set','lo','up')
        run('sysctl','-qw','net.ipv4.ip_forward=1')
        for namespace,device,remote,address,peer in (
            (peers[0],'wg_direct','pc0','10.77.0.2/24','10.77.0.10/24'),
            (peers[1],'plant','plc0','192.168.10.254/24','192.168.10.8/24')):
            run('ip','netns','add',namespace); created.append(namespace)
            run('ip','link','add',device,'type','veth','peer','name',remote)
            run('ip','link','set',remote,'netns',namespace)
            run('ip','addr','add',address,'dev',device)
            run('ip','link','set',device,'up')
            run('ip','-n',namespace,'link','set','lo','up')
            run('ip','-n',namespace,'addr','add',peer,'dev',remote)
            run('ip','-n',namespace,'link','set',remote,'up')
        run('ip','-n',peers[0],'route','add','192.168.10.0/24','via','10.77.0.2')
        run('ip','-n',peers[1],'route','add','default','via','192.168.10.254')
        policy('on')
        spawn(None,ECHO,443); spawn(peers[1],ECHO,2502)
        https=spawn(peers[0],CLIENT,'10.77.0.2',443)
        plant=spawn(peers[0],CLIENT,'192.168.10.8',2502)
        exchange(https,'https-before','https-before')
        exchange(plant,'plant-before','plant-before')
        policy('unprotected')
        exchange(https,'reproduce-old-https-bypass','reproduce-old-https-bypass')
        exchange(plant,'reproduce-old-plant-bypass','reproduce-old-plant-bypass')
        policy('plant')
        exchange(https,'https-revoked','BLOCKED')
        exchange(plant,'plant-still-allowed','plant-still-allowed')
        policy('changed')
        exchange(plant,'old-plant-revoked','BLOCKED')
        second_https=spawn(peers[0],CLIENT,'10.77.0.2',443)
        exchange(second_https,'https-reenabled','https-reenabled')
        policy('off')
        exchange(second_https,'all-revoked','BLOCKED')
        print('Native nft syntax, HTTPS revocation, independent plant access and stale-plant established-flow denial PASS')
    finally:
        for child in reversed(children):
            child.terminate()
            try: child.communicate(timeout=3)
            except subprocess.TimeoutExpired: child.kill(); child.communicate()
        for namespace in reversed(created):
            subprocess.run(['ip','netns','del',namespace],capture_output=True)


if __name__=='__main__':
    main()
