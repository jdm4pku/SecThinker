from pathlib import Path
import os,subprocess,json,sys
R=Path(__file__).resolve().parents[2];node=sys.argv[1];rt=R/'runtime/sonarqube'/node
for n in ['tmp','data','logs','home','cache','pid']:(rt/n).mkdir(parents=True,exist_ok=True)
sonar=R/'tools/prompt_eval/sonarqube-26.10.0.133078';jdk=next((R/'tools/prompt_eval').glob('zulu21*-jdk*'))
props={'sonar.web.host':'127.0.0.1','sonar.web.port':'19000','sonar.search.port':'19001','sonar.path.data':str(rt/'data'),'sonar.path.temp':str(rt/'tmp'),'sonar.path.logs':str(rt/'logs'),'sonar.telemetry.enable':'false','sonar.web.javaOpts':'-Xmx1g -Xms256m','sonar.ce.javaOpts':'-Xmx2g -Xms256m','sonar.search.javaOpts':'-Xmx1g -Xms1g'}
(sonar/'conf/sonar.properties').write_text('\n'.join(k+'='+v for k,v in props.items())+'\n')
env={**os.environ,'SONAR_JAVA_PATH':str(jdk/'bin/java'),'JAVA_HOME':str(jdk),'TMPDIR':str(rt/'tmp'),'PIDDIR':str(rt/'pid'),'XDG_CACHE_HOME':str(rt/'cache'),'JAVA_TOOL_OPTIONS':'-Djava.io.tmpdir='+str(rt/'tmp')+' -Duser.home='+str(rt/'home')+' -XX:-UsePerfData'}
def nonroot():os.setgroups([]);os.setgid(900004);os.setuid(190007)
with open(rt/'console.log','a') as log:c=subprocess.Popen(['/bin/sh',str(sonar/'bin/linux-x86-64/sonar.sh'),'console'],env=env,cwd=sonar,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=nonroot)
(rt/'launcher.pid').write_text(str(c.pid));print('Sonar started',node,c.pid)
