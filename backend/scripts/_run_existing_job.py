import sys
sys.path.insert(0,'.')
from app.core.config import get_settings
from app.jobs.store import JobStore
from app.jobs.models import JobStage
from app.pipeline.run import execute_pipeline
s=get_settings(); st=JobStore(s.output_dir_path)
jid=sys.argv[1]
j=st.get(jid); j.stage=JobStage.UPLOADED; j.error=None; j.attempts=0; st.update(j)
execute_pipeline(jid, st, s)
print("finished", st.get(jid).stage)
