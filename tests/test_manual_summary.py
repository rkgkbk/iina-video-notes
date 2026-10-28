import importlib.util,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('worker', 'AI-Video.iinaplugin/worker.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp);video=root/'video.mp4';video.write_bytes(b'test');cache=root/'cache';cache.mkdir()
 _,job=w.job_path(video,cache);job.mkdir()
 (job/'transcript.json').write_text(json.dumps({'segments':[{'start':0,'end':1,'text':'测试'}],'complete':True,'duration':1}))
 args=['worker','run','--video',str(video),'--cache',str(cache),'--cancel',str(root/'cancel')]
 events=[]
 with patch.object(sys,'argv',args),patch.object(w,'emit',side_effect=lambda kind,**kw:events.append(kind)),patch.object(w,'codex_summary',side_effect=AssertionError('Automatic Codex call')):
  w.main()
 assert 'transcription_done' in events
 with patch.object(sys,'argv',args+['--mode','summarize']),patch.object(w,'emit'),patch.object(w,'codex_summary',return_value='手动总结') as summary:
  w.main();summary.assert_called_once()
 assert json.loads((w.summary_path(job)/'result.json').read_text())['summary']=='手动总结'
print('PASS: transcription never calls Codex; explicit summarize generates result')
