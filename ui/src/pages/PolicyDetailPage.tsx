import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'

function pretty(obj: any) {
  return JSON.stringify(obj ?? {}, null, 2)
}

export default function PolicyDetailPage() {
  const { policyId } = useParams()
  const nav = useNavigate()
  const isNew = policyId === 'new'

  const q = useQuery({
    queryKey: ['policy', policyId],
    enabled: !!policyId && !isNew,
    queryFn: () => api.getPolicy(policyId!)
  })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [schemaVersion, setSchemaVersion] = useState('1')
  const [isActive, setIsActive] = useState(true)
  const [documentText, setDocumentText] = useState('{}')
  const [status, setStatus] = useState<string>('')

  useEffect(() => {
    if (!q.data) return
    setName(q.data.name || '')
    setDescription(q.data.description || '')
    setSchemaVersion(q.data.schema_version || '1')
    setIsActive(!!q.data.is_active)
    setDocumentText(pretty(q.data.document))
  }, [q.data])

  const parsedDoc = useMemo(() => {
    try {
      return { ok: true, value: JSON.parse(documentText || '{}') }
    } catch (e: any) {
      return { ok: false, error: e?.message || String(e) }
    }
  }, [documentText])

  const m = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('name required')
      if (!parsedDoc.ok) throw new Error(`document JSON invalid: ${parsedDoc.error}`)
      return api.upsertPolicy({
        name: name.trim(),
        description: description || null,
        schema_version: schemaVersion || '1',
        is_active: isActive,
        document: parsedDoc.value
      })
    },
    onSuccess: (resp) => {
      setStatus('Saved')
      const id = resp?.policy?.id
      if (id) nav(`/policies/${id}`)
    },
    onError: (e: any) => {
      setStatus(JSON.stringify(e, null, 2))
    }
  })

  if (!isNew && q.isLoading) return <div>Loading…</div>
  if (!isNew && q.isError) return <pre>{JSON.stringify(q.error, null, 2)}</pre>

  return (
    <div style={{ maxWidth: 920 }}>
      <h2 style={{ marginTop: 0 }}>{isNew ? 'New policy' : 'Policy'}</h2>

      <div style={{ display: 'grid', gap: 12 }}>
        <label>
          <div>Name</div>
          <input style={{ width: '100%', padding: 8 }} value={name} onChange={(e) => setName(e.target.value)} />
        </label>

        <label>
          <div>Description</div>
          <input style={{ width: '100%', padding: 8 }} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>

        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <label>
            <div>Schema version</div>
            <input style={{ width: 120, padding: 8 }} value={schemaVersion} onChange={(e) => setSchemaVersion(e.target.value)} />
          </label>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 18 }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
          </label>
        </div>

        <label>
          <div>Document (JSON)</div>
          <textarea
            style={{ width: '100%', minHeight: 360, padding: 8, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace' }}
            value={documentText}
            onChange={(e) => setDocumentText(e.target.value)}
          />
          {!parsedDoc.ok ? (
            <div style={{ color: 'crimson', fontSize: 12 }}>JSON parse error: {parsedDoc.error}</div>
          ) : null}
        </label>

        <div style={{ display: 'flex', gap: 12 }}>
          <button disabled={m.isPending || !parsedDoc.ok} onClick={() => m.mutate()} style={{ padding: '10px 12px' }}>
            {m.isPending ? 'Saving…' : 'Save'}
          </button>
          <button onClick={() => nav('/policies')} style={{ padding: '10px 12px' }}>
            Back
          </button>
        </div>

        {status ? <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{status}</pre> : null}
      </div>
    </div>
  )
}
