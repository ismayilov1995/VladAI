import { useCallback, useRef, useState } from 'react'

interface Props {
  filename: string | null
  busy: boolean
  onFile: (file: File) => void
}

export function DropZone({ filename, busy, onFile }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [over, setOver] = useState(false)

  const take = useCallback((files: FileList | null) => {
    const file = files?.[0]
    if (file) onFile(file)
  }, [onFile])

  return (
    <div
      onDragOver={(event) => { event.preventDefault(); setOver(true) }}
      onDragLeave={() => { setOver(false) }}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        take(event.dataTransfer.files)
      }}
      onClick={() => { inputRef.current?.click() }}
      className={[
        'cursor-pointer rounded-lg border border-dashed px-3 py-4 text-center transition',
        over ? 'border-amber-400 bg-amber-400/10' : 'border-neutral-700 hover:border-neutral-600',
      ].join(' ')}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".svg,image/svg+xml"
        className="hidden"
        onChange={(event) => { take(event.target.files) }}
      />
      {filename ? (
        <>
          <p className="truncate text-sm text-neutral-200" title={filename}>{filename}</p>
          <p className="mt-0.5 text-[11px] text-neutral-500">
            {busy ? 'reading…' : 'click or drop to replace'}
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-neutral-300">Drop a panel SVG</p>
          <p className="mt-0.5 text-[11px] text-neutral-500">
            needs an <code className="font-mono">id="calib"</code> element for scale
          </p>
        </>
      )}
    </div>
  )
}
