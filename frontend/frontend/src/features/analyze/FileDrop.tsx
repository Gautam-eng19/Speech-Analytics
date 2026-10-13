import { useMemo, useRef, useState } from 'react';
import { Icon } from '@/components/Icon';
import { Button } from '@/components/ui';
import { fmtBytes } from '@/lib/format';
import { PreviewPlayer } from './PreviewPlayer';

/** A static, decorative trace behind the drop area. It carries no data. */
function ScopeBackdrop() {
  const d = useMemo(() => {
    let path = '';
    for (let i = 0; i <= 240; i++) {
      const x = (i / 240) * 600;
      const env = Math.sin((i / 240) * Math.PI) ** 1.4;
      const y = 60 + env * (Math.sin(i * 0.9) * 22 + Math.sin(i * 2.3) * 9 + Math.sin(i * 0.31) * 14);
      path += `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
    }
    return path;
  }, []);
  return (
    <svg className="drop__scope" viewBox="0 0 600 120" preserveAspectRatio="none" aria-hidden="true">
      {[30, 60, 90].map((y) => <line key={y} x1={0} x2={600} y1={y} y2={y} />)}
      <path d={d} />
    </svg>
  );
}


/** The upload area: drop a file or choose one; the chosen file is shown with a preview player. Validation is the page's job. */
export function FileDrop({ file, onFile, onClear }: { file: File | null; onFile: (file: File | undefined) => void; onClear: () => void }) {
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const depth = useRef(0);
  return (
    <div
      className={`drop ${dragging ? 'is-over' : ''} ${file ? 'has-file' : ''}`}
      onDragEnter={(e) => { e.preventDefault(); depth.current += 1; setDragging(true); }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => { depth.current = Math.max(0, depth.current - 1); if (depth.current === 0) setDragging(false); }}
      onDrop={(e) => { e.preventDefault(); depth.current = 0; setDragging(false); onFile(e.dataTransfer.files[0]); }}
    >
      <span className="drop__corner drop__corner--tl" /><span className="drop__corner drop__corner--tr" /><span className="drop__corner drop__corner--bl" /><span className="drop__corner drop__corner--br" />
      <ScopeBackdrop />
      {file ? (
        <div className="drop__file">
          <div className="drop__file-head">
            <Icon name="file-audio" size={22} />
            <div className="drop__file-meta">
              <div className="drop__file-name truncate" title={file.name}>{file.name}</div>
              <div className="muted num">{fmtBytes(file.size)}</div>
            </div>
            <Button size="sm" variant="ghost" onClick={() => picker.current?.click()}>Replace</Button>
            <Button size="sm" variant="ghost" icon="x" onClick={onClear} aria-label="Remove the file" />
          </div>
          <PreviewPlayer file={file} />
        </div>
      ) : (
        <div className="drop__prompt">
          <div className="drop__icon"><Icon name="upload" size={22} /></div>
          <div className="drop__title">Drop a WAV or MP3 here</div>
          <p className="drop__hint">or <button type="button" className="link-btn" onClick={() => picker.current?.click()}>choose a file</button>. The audio is analysed in memory and is not saved; only the result is kept.</p>
        </div>
      )}
      <input ref={picker} className="sr-only" type="file" aria-label="Choose an audio file (WAV or MP3)" accept=".wav,.mp3,audio/wav,audio/x-wav,audio/mpeg" tabIndex={-1} onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ''; }} />
    </div>
  );
}
