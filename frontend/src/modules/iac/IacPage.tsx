import { useEffect, useState } from 'react';
import { Copy, FileCode2, Search } from 'lucide-react';
import { post } from '../../lib/api';
import { useApi } from '../../lib/useApi';
import { dateTime, number, percent, shortType } from '../../lib/format';
import type { IacFile, IacResult, InventoryPage, InventoryResource, ManualCreations, TerraformCoverage } from '../../lib/types';
import { useApp } from '../../state/hooks';
import {
  Badge, Card, Empty, ErrorState, Loading, Meter, Modal, Notice, PageHeader, Pagination, Section, StatTile, Tabs,
} from '../../components/ui';

const FILES: { id: IacFile; label: string }[] = [
  { id: 'main_tf', label: 'main.tf' },
  { id: 'providers_tf', label: 'providers.tf' },
  { id: 'variables_tf', label: 'variables.tf' },
  { id: 'outputs_tf', label: 'outputs.tf' },
  { id: 'terraform_tfvars', label: 'terraform.tfvars' },
  { id: 'backend_hcl', label: 'backend.hcl' },
];

type Env = 'dev' | 'qa' | 'prod';
type Domain = 'networking' | 'platform' | 'data' | 'security';

function guessEnv(r: InventoryResource): Env {
  const s = `${r.environment ?? ''} ${r.resourceGroup} ${r.subscriptionName}`.toLowerCase();
  return s.includes('prod') ? 'prod' : s.includes('qa') ? 'qa' : 'dev';
}

function guessDomain(r: InventoryResource): Domain {
  const t = r.type.toLowerCase();
  if (/network|publicip|dns|frontdoor|loadbalancer/.test(t)) return 'networking';
  if (/sql|storage|database|cosmos|redis/.test(t)) return 'data';
  if (/vault|security|policy/.test(t)) return 'security';
  return 'platform';
}

function Generator({ resource, onClose }: { resource: InventoryResource; onClose: () => void }) {
  const { toast } = useApp();
  const [env, setEnv] = useState<Env>(guessEnv(resource));
  const [domain, setDomain] = useState<Domain>(guessDomain(resource));
  const [file, setFile] = useState<IacFile>('main_tf');
  // La generación depende de (recurso, ambiente, dominio). Mientras llega la
  // nueva se sigue mostrando la anterior.
  const params = `${resource.id}|${env}|${domain}`;
  const [generated, setGenerated] = useState<{ params: string; result: IacResult | null; error: string | null } | null>(null);
  const busy = generated?.params !== params;
  const result = generated?.result ?? null;
  const error = busy ? null : generated.error;

  useEffect(() => {
    let vigente = true;
    post<IacResult>('/api/iac/generate', { resource_id: resource.id, environment: env, domain })
      .then((r) => vigente && setGenerated({ params, result: r, error: null }))
      .catch((e) => vigente && setGenerated((prev) => ({ params, result: prev?.result ?? null, error: e.message })));
    return () => {
      vigente = false;
    };
  }, [params, resource.id, env, domain]);

  const code = result?.[file] ?? '';
  const folder = `stacks/${resource.subscriptionName.toLowerCase().replace(/[^a-z0-9]+/g, '-')}/${env}/${domain}/`;

  return (
    <Modal
      title="Generar Terraform"
      subtitle={<><span className="mono">{resource.name}</span> · {resource.type}</>}
      onClose={onClose}
      footer={
        <>
          <span className="muted" style={{ marginRight: 'auto', fontSize: 12.5 }}>
            {result && <>Generado con {result.generation_mode.startsWith('llm_') ? 'IA' : 'plantillas locales'} · carpeta sugerida <code>{folder}</code></>}
          </span>
          <button className="btn" onClick={onClose}>Cerrar</button>
        </>
      }
    >
      <div className="toolbar">
        <label className="stack" style={{ gap: 4 }}>
          <span className="muted" style={{ fontSize: 12 }}>Ambiente</span>
          <select className="select" value={env} onChange={(e) => setEnv(e.target.value as Env)}>
            <option value="dev">dev</option><option value="qa">qa</option><option value="prod">prod</option>
          </select>
        </label>
        <label className="stack" style={{ gap: 4 }}>
          <span className="muted" style={{ fontSize: 12 }}>Dominio</span>
          <select className="select" value={domain} onChange={(e) => setDomain(e.target.value as Domain)}>
            <option value="platform">platform</option><option value="networking">networking</option>
            <option value="data">data</option><option value="security">security</option>
          </select>
        </label>
      </div>
      <Notice>Revisa el código y ejecuta <code>terraform plan</code>: el bloque <code>import</code> adopta el recurso existente, y el plan no debería proponer cambios antes de integrarlo.</Notice>
      <Tabs<IacFile> tabs={FILES} value={file} onChange={setFile} />
      {busy ? <Loading label="Generando configuración…" /> : error ? <ErrorState error={error} /> : (
        <div style={{ position: 'relative' }}>
          <button
            className="btn btn-sm"
            style={{ position: 'absolute', top: 8, right: 8 }}
            onClick={() => navigator.clipboard.writeText(code).then(() => toast('Código copiado'))}
          >
            <Copy size={13} /> Copiar
          </button>
          <pre className="code-block">{code}</pre>
        </div>
      )}
    </Modal>
  );
}

const PAGE_SIZE = 15;

export function IacPage() {
  const { scope, scopeKey } = useApp();
  const coverage = useApi<TerraformCoverage>(`tfcov:${scopeKey}`, () => post('/api/iac/terraform-coverage', { subscriptionIds: scope }));
  const manual = useApi<ManualCreations>(`manual:${scopeKey}`, () => post('/api/inventory/manual-creations', { subscriptionIds: scope }));
  const [search, setSearch] = useState('');
  const [onlyShadow, setOnlyShadow] = useState(true);
  const [page, setPage] = useState(1);
  const filters = { search, onlyShadowItCandidates: onlyShadow };
  const candidates = useApi<InventoryPage>(
    `iac-cand:${scopeKey}:${search}:${onlyShadow}:${page}`,
    () => post('/api/inventory/resources', { subscriptionIds: scope, filters, page, pageSize: PAGE_SIZE }),
  );
  const [target, setTarget] = useState<InventoryResource | null>(null);

  const c = coverage.data;
  const m = manual.data;

  return (
    <>
      <PageHeader
        title="Infraestructura como código"
        description="Qué parte del inventario está realmente en Terraform, según sus estados, quién creó recursos a mano y el generador de HCL para codificar lo que falta."
      />

      {coverage.loading && <Loading label="Leyendo los estados de Terraform…" />}
      {coverage.error && !c && <ErrorState error={coverage.error} onRetry={coverage.reload} />}

      {c && (
        <>
          {!c.available && <Notice tone="warning">{c.message}</Notice>}
          {c.sources_failed?.length ? <Notice tone="warning">No se pudieron leer: {c.sources_failed.join('; ')}</Notice> : null}
          <div className="grid grid-4">
            <div className="card stat">
              <div className="stat-label">Gestionado por Terraform</div>
              <div className="stat-value">{c.available ? percent(c.coverage_percentage) : '—'}</div>
              <Meter value={c.coverage_percentage} />
              <div className="stat-meta">{number(c.managed_in_inventory)} de {number(c.total_resources)} recursos aparecen en un estado</div>
            </div>
            <StatTile refreshing={coverage.refreshing} label="Sin estado que los gestione" value={number(c.unmanaged_count)} meta="Pueden tener su estado en otra cuenta" />
            <StatTile refreshing={coverage.refreshing} label="Ids obsoletos" value={number(c.stale_ids)} meta="En un estado pero ya no existen en Azure" />
            <StatTile refreshing={coverage.refreshing} label="Estados leídos" value={number(c.states_read)} meta={c.states_failed ? `${c.states_failed} con error` : 'Sin errores de lectura'} />
          </div>
        </>
      )}

      <div className="grid grid-2">
        <Card title="Estados de Terraform" subtitle="Solo se extraen ids y tipos; el resto del estado se descarta." flush refreshing={coverage.refreshing}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Estado</th><th className="num">Recursos</th></tr></thead>
              <tbody>
                {c?.states.map((s) => (
                  <tr key={s.name}>
                    <td className="mono" style={{ fontSize: 12 }}>{s.name}</td>
                    <td className="num">{s.ok ? number(s.resources) : <span className="muted">{s.reason ?? 'error'}</span>}</td>
                  </tr>
                ))}
                {c && !c.states.length && <tr><td colSpan={2} className="table-empty">No hay estados configurados (TFSTATE_ACCOUNT).</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
        <Card
          title="Creados a mano, con evidencia"
          subtitle={m?.available ? `Historial de cambios de Azure · ${m.windowFrom?.slice(0, 10)} a ${m.windowTo?.slice(0, 10)}` : 'Historial de cambios de Azure (unos 14 días)'}
          flush
          refreshing={manual.refreshing}
        >
          {m?.available ? (
            <>
              <div className="toolbar" style={{ padding: '0 14px 10px' }}>
                <Badge><span className="dot dot-serious" />{number(m.manualCount)} por personas</Badge>
                <Badge><span className="dot dot-good" />{number(m.automatedCount)} por automatización</Badge>
              </div>
              <p className="muted" style={{ fontSize: 12.5, padding: '0 14px 10px' }}>
                Azure registra la identidad, no la herramienta: Terraform ejecutado con una sesión personal
                (<code>az login</code>) también aparece como persona. Cruza con la cobertura de los estados antes de concluir.
              </p>
              <div className="table-wrap" style={{ maxHeight: 300, overflowY: 'auto' }}>
                <table className="table">
                  <thead><tr><th>Recurso</th><th>Creado por</th><th>Cuándo</th></tr></thead>
                  <tbody>
                    {m.manualCreations.map((x, i) => (
                      <tr key={`${x.id}-${x.createdAt}-${i}`}>
                        <td><span className="primary-cell">{x.name}</span><span className="sub">{shortType(x.type)}</span></td>
                        <td className="secondary truncate" style={{ maxWidth: 200 }}>{x.createdBy}</td>
                        <td className="secondary" style={{ whiteSpace: 'nowrap' }}>{dateTime(x.createdAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : manual.loading ? <Loading /> : <Empty>Sin eventos de creación en la ventana que Azure conserva.</Empty>}
        </Card>
      </div>

      <Section title="Codificar recursos" description="Genera el HCL con bloque import para adoptar un recurso existente en Terraform sin recrearlo.">
        <Card flush refreshing={candidates.refreshing}>
          <div className="toolbar" style={{ padding: '0 14px 12px' }}>
            <div className="input-icon grow">
              <Search size={14} />
              <input className="input" placeholder="Buscar recurso" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Buscar recurso" />
            </div>
            <label className="check">
              <input type="checkbox" checked={onlyShadow} onChange={(e) => { setOnlyShadow(e.target.checked); setPage(1); }} /> Solo candidatos a Shadow IT
            </label>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Recurso</th><th>Tipo</th><th>Suscripción</th><th>Tags</th><th /></tr></thead>
              <tbody>
                {candidates.data?.items.map((r) => (
                  <tr key={r.id}>
                    <td><span className="primary-cell">{r.name}</span><span className="sub">{r.resourceGroup}</span></td>
                    <td className="secondary">{r.typeDisplayName || shortType(r.type)}</td>
                    <td className="secondary">{r.subscriptionName}</td>
                    <td className="secondary num">{r.mandatoryTags.present}/{r.mandatoryTags.totalRequired}</td>
                    <td>
                      <div className="row-actions">
                        <button className="btn btn-sm" onClick={() => setTarget(r)}><FileCode2 size={13} /> Generar HCL</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {candidates.data && !candidates.data.items.length && (
                  <tr><td colSpan={5} className="table-empty">{onlyShadow ? 'No hay candidatos a Shadow IT. Desmarca el filtro para codificar cualquier recurso.' : 'Sin resultados.'}</td></tr>
                )}
                {candidates.loading && <tr><td colSpan={5}><Loading /></td></tr>}
              </tbody>
            </table>
          </div>
          {candidates.data && <Pagination page={page} pageSize={PAGE_SIZE} total={candidates.data.total} onPage={setPage} />}
        </Card>
      </Section>

      {target && <Generator resource={target} onClose={() => setTarget(null)} />}
    </>
  );
}
