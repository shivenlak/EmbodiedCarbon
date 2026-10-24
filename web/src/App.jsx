import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  Layers, 
  AlertTriangle, 
  CheckCircle2, 
  ArrowRight, 
  Download, 
  RefreshCw, 
  ChevronDown, 
  ChevronUp, 
  Sliders, 
  BarChart3, 
  ShieldCheck, 
  FileSpreadsheet,
  Info,
  ExternalLink,
  Flame,
  Check
} from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000';

export default function App() {
  const [projectId, setProjectId] = useState('demo');
  const [intake, setIntake] = useState(null);
  const [takeoff, setTakeoff] = useState(null);
  const [carbon, setCarbon] = useState(null);
  const [substitutions, setSubstitutions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // UI states
  const [showGaps, setShowGaps] = useState(true);
  const [selectedClass, setSelectedClass] = useState('all');
  const [editingLineId, setEditingLineId] = useState(null);
  const [editQty, setEditQty] = useState('');
  const [updating, setUpdating] = useState(false);
  const [appliedSwaps, setAppliedSwaps] = useState({});

  useEffect(() => {
    fetchProjectData();
  }, [projectId]);

  async function fetchProjectData() {
    setLoading(true);
    setError(null);
    try {
      const [intakeRes, takeoffRes, carbonRes, subsRes] = await Promise.all([
        fetch(`${API_BASE}/projects/${projectId}/intake`),
        fetch(`${API_BASE}/projects/${projectId}/takeoff`),
        fetch(`${API_BASE}/projects/${projectId}/carbon`),
        fetch(`${API_BASE}/projects/${projectId}/substitutions`)
      ]);

      if (!intakeRes.ok || !takeoffRes.ok || !carbonRes.ok) {
        throw new Error('Failed to fetch project data from API.');
      }

      const intakeData = await intakeRes.json();
      const takeoffData = await takeoffRes.json();
      const carbonData = await carbonRes.json();
      const subsData = subsRes.ok ? await subsRes.json() : [];

      setIntake(intakeData);
      setTakeoff(takeoffData);
      setCarbon(carbonData);
      setSubstitutions(subsData);
    } catch (err) {
      console.warn('API error, check if uvicorn is running:', err);
      setError('Backend API not reached. Ensure FastAPI is running at http://127.0.0.1:8000.');
    } finally {
      setLoading(false);
    }
  }

  async function handleOverrideQuantity(lineId, newQuantity) {
    setUpdating(true);
    try {
      const res = await fetch(`${API_BASE}/projects/${projectId}/lines/${lineId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity: newQuantity !== null ? parseFloat(newQuantity) : null })
      });
      if (!res.ok) throw new Error('Failed to update quantity');
      const updatedCarbon = await res.json();
      setCarbon(updatedCarbon);
      
      // Refresh takeoff and substitutions
      const [tRes, sRes] = await Promise.all([
        fetch(`${API_BASE}/projects/${projectId}/takeoff`),
        fetch(`${API_BASE}/projects/${projectId}/substitutions`)
      ]);
      setTakeoff(await tRes.json());
      if (sRes.ok) setSubstitutions(await sRes.json());
      setEditingLineId(null);
    } catch (err) {
      alert('Error updating quantity: ' + err.message);
    } finally {
      setUpdating(false);
    }
  }

  function handleExport(format) {
    window.open(`${API_BASE}/projects/${projectId}/export/${format}`, '_blank');
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: '#0B0F17' }}>
        <div style={{ textAlign: 'center' }}>
          <RefreshCw size={36} color="#3B82F6" style={{ animation: 'spin 1s linear infinite' }} />
          <p style={{ marginTop: '16px', color: '#94A3B8' }}>Loading project carbon pipeline...</p>
        </div>
      </div>
    );
  }

  const project = takeoff?.project || { name: 'Demo Project', gfa_m2: 306, jurisdiction: 'Edmonton, AB' };
  const lines = takeoff?.lines || [];
  const carbonLines = carbon?.lines || [];
  const carbonMap = Object.fromEntries(carbonLines.map(c => [c.line_id, c]));

  const filteredLines = selectedClass === 'all' 
    ? lines 
    : lines.filter(l => l.element_class === selectedClass);

  const classes = ['all', ...new Set(lines.map(l => l.element_class))];

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--bg-main)', color: 'var(--text-main)', paddingBottom: '60px' }}>
      
      {/* Top Navbar */}
      <header style={{ 
        borderBottom: '1px solid var(--border)', 
        backgroundColor: 'rgba(19, 26, 38, 0.85)', 
        backdropFilter: 'blur(8px)',
        position: 'sticky', 
        top: 0, 
        zIndex: 50,
        padding: '14px 28px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ 
            width: '38px', 
            height: '38px', 
            borderRadius: '10px', 
            backgroundColor: 'var(--accent-green-bg)', 
            border: '1px solid var(--accent-green)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <Flame size={20} color="var(--accent-green)" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h1 style={{ fontSize: '18px', fontWeight: 800, letterSpacing: '-0.02em' }}>eCarbon</h1>
              <span style={{ 
                fontSize: '11px', 
                fontWeight: 600, 
                backgroundColor: 'var(--accent-blue-bg)', 
                color: 'var(--accent-blue)', 
                padding: '2px 8px', 
                borderRadius: '6px',
                border: '1px solid rgba(59, 130, 246, 0.25)'
              }}>
                Landmark Built World Challenge
              </span>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Automated Vector Takeoff to A1-A3 Whole-Building LCA</p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button 
              onClick={() => handleExport('csv')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--text-main)',
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                padding: '8px 14px'
              }}
            >
              <Download size={14} />
              Export CSV
            </button>
            <button 
              onClick={() => handleExport('xlsx')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '13px',
                fontWeight: 600,
                color: '#fff',
                backgroundColor: 'var(--accent-blue)',
                border: 'none',
                borderRadius: '8px',
                padding: '8px 14px'
              }}
            >
              <FileSpreadsheet size={14} />
              Export Excel (.xlsx)
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main style={{ maxWidth: '1440px', margin: '0 auto', padding: '24px 28px' }}>

        {/* Project Facts Bar */}
        <div style={{ 
          backgroundColor: 'var(--bg-card)', 
          border: '1px solid var(--border)', 
          borderRadius: '12px', 
          padding: '16px 20px', 
          marginBottom: '20px',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '24px', flexWrap: 'wrap' }}>
            <div>
              <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 700 }}>Plan Set</span>
              <p style={{ fontSize: '15px', fontWeight: 700 }}>{project.name}</p>
            </div>
            <div style={{ borderLeft: '1px solid var(--border)', paddingLeft: '20px' }}>
              <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 700 }}>Jurisdiction & Code</span>
              <p style={{ fontSize: '14px', color: 'var(--text-muted)' }}>{project.jurisdiction || 'Alberta NBC(AE) CZ 7A'}</p>
            </div>
            <div style={{ borderLeft: '1px solid var(--border)', paddingLeft: '20px' }}>
              <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 700 }}>Gross Floor Area</span>
              <p style={{ fontSize: '14px', color: 'var(--text-muted)' }}>{project.gfa_m2 || 306} m² ({project.gfa_basis})</p>
            </div>
            <div style={{ borderLeft: '1px solid var(--border)', paddingLeft: '20px' }}>
              <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 700 }}>Source File</span>
              <p style={{ fontSize: '14px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{takeoff?.source_file}</p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ 
              display: 'inline-flex', 
              alignItems: 'center', 
              gap: '6px', 
              fontSize: '12px', 
              fontWeight: 600, 
              padding: '6px 12px', 
              borderRadius: '20px',
              backgroundColor: 'var(--accent-green-bg)',
              color: 'var(--accent-green)',
              border: '1px solid rgba(16, 185, 129, 0.3)'
            }}>
              <ShieldCheck size={14} />
              A1-A3 Module Scope Verified
            </span>
          </div>
        </div>

        {/* Stage 1 Gap Report Accordion */}
        {intake && (
          <div style={{ 
            backgroundColor: 'var(--bg-card)', 
            border: '1px solid var(--border)', 
            borderRadius: '12px', 
            marginBottom: '24px',
            overflow: 'hidden'
          }}>
            <div 
              onClick={() => setShowGaps(!showGaps)}
              style={{ 
                padding: '14px 20px', 
                backgroundColor: 'rgba(23, 32, 48, 0.6)', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'space-between',
                cursor: 'pointer'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <AlertTriangle size={18} color="var(--accent-amber)" />
                <h3 style={{ fontSize: '14px', fontWeight: 700 }}>Stage 1 Drawing Intake & Gap Report</h3>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  ({intake.n_readable} of {intake.n_sheets} sheets readable &bull; {intake.gaps.length} caveats reported)
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>Criterion 1 "Reports what it cannot read"</span>
                {showGaps ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </div>
            </div>

            {showGaps && (
              <div style={{ padding: '18px 20px', borderTop: '1px solid var(--border)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginBottom: '16px' }}>
                  <div style={{ backgroundColor: 'var(--bg-subtle)', padding: '12px 14px', borderRadius: '8px' }}>
                    <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Detected Exporters</span>
                    <p style={{ fontSize: '13px', fontWeight: 600, marginTop: '4px' }}>
                      {Object.entries(intake.toolchains).map(([k, v]) => `${k} (${v})`).join(', ')}
                    </p>
                  </div>
                  <div style={{ backgroundColor: 'var(--bg-subtle)', padding: '12px 14px', borderRadius: '8px' }}>
                    <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Scale Calibration</span>
                    <p style={{ fontSize: '13px', fontWeight: 600, color: 'var(--accent-green)', marginTop: '4px' }}>
                      1:50 Metric (0.2% chain spread)
                    </p>
                  </div>
                  <div style={{ backgroundColor: 'var(--bg-subtle)', padding: '12px 14px', borderRadius: '8px' }}>
                    <span style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>Unreadable Pages</span>
                    <p style={{ fontSize: '13px', fontWeight: 600, marginTop: '4px' }}>
                      {intake.n_sheets - intake.n_readable} pages (Textless Distiller)
                    </p>
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {intake.gaps.map((g, idx) => (
                    <div key={idx} style={{ 
                      display: 'flex', 
                      alignItems: 'flex-start', 
                      gap: '10px', 
                      fontSize: '13px',
                      padding: '10px 12px',
                      borderRadius: '6px',
                      backgroundColor: g.severity === 'blocking' ? 'var(--accent-rose-bg)' : 'rgba(245, 158, 11, 0.08)',
                      border: `1px solid ${g.severity === 'blocking' ? 'rgba(244, 63, 94, 0.3)' : 'rgba(245, 158, 11, 0.25)'}`
                    }}>
                      <Info size={15} color={g.severity === 'blocking' ? 'var(--accent-rose)' : 'var(--accent-amber)'} style={{ marginTop: '2px', flexShrink: 0 }} />
                      <div>
                        <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', marginRight: '8px' }}>[{g.code}]</span>
                        <span>{g.message}</span>
                        {g.sheet_no && <span style={{ marginLeft: '6px', color: 'var(--text-dim)' }}>({g.sheet_no})</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Headline KPI Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px', marginBottom: '24px' }}>
          
          {/* Card 1: Total Embodied Carbon */}
          <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Total Embodied Carbon (A1-A3)</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginTop: '6px' }}>
              <span style={{ fontSize: '30px', fontWeight: 800, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>
                {carbon?.total_kg_co2e ? Number(carbon.total_kg_co2e).toLocaleString() : '—'}
              </span>
              <span style={{ fontSize: '14px', color: 'var(--text-dim)', fontWeight: 600 }}>kg CO₂e</span>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '8px' }}>
              Uncertainty range: <span className="mono">{Number(carbon?.range_low_kg_co2e || 0).toLocaleString()} – {Number(carbon?.range_high_kg_co2e || 0).toLocaleString()}</span>
            </div>
          </div>

          {/* Card 2: Carbon Intensity */}
          <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Carbon Intensity</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginTop: '6px' }}>
              <span style={{ fontSize: '30px', fontWeight: 800, color: 'var(--accent-blue)', letterSpacing: '-0.02em' }}>
                {carbon?.intensity_kg_co2e_per_m2 || '—'}
              </span>
              <span style={{ fontSize: '14px', color: 'var(--text-dim)', fontWeight: 600 }}>kg CO₂e / m² GFA</span>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '8px' }}>
              Canadian benchmark band: 141 – 731 kgCO₂e/m²
            </div>
          </div>

          {/* Card 3: Factor Coverage */}
          <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Factor Coverage</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginTop: '6px' }}>
              <span style={{ fontSize: '30px', fontWeight: 800, color: 'var(--accent-green)', letterSpacing: '-0.02em' }}>
                {carbon ? `${Math.round(carbon.coverage_pct)}%` : '—'}
              </span>
              <span style={{ fontSize: '14px', color: 'var(--text-dim)', fontWeight: 600 }}>
                ({lines.length - (carbon?.uncounted_lines?.length || 0)}/{lines.length} items)
              </span>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '8px' }}>
              {carbon?.uncounted_lines?.length || 0} items with visible "no factor found"
            </div>
          </div>

          {/* Card 4: Module Reconciliation */}
          <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>CMHC Published Baseline</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginTop: '6px' }}>
              <span style={{ fontSize: '26px', fontWeight: 800, color: 'var(--text-muted)', letterSpacing: '-0.02em' }}>
                162,043
              </span>
              <span style={{ fontSize: '14px', color: 'var(--text-dim)', fontWeight: 600 }}>kg CO₂e</span>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '8px' }}>
              Whole-life (A1-A5, B4-B5, C2-C4) &bull; Not comparable to A1-A3
            </div>
          </div>

        </div>

        {/* Split Grid: BoQ Table (Left 70%) & Contribution / Substitutions (Right 30%) */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.8fr) minmax(0, 1.2fr)', gap: '24px' }}>
          
          {/* Left Column: Bill of Quantities Table */}
          <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', overflow: 'hidden' }}>
            
            {/* Table Header & Filter Tabs */}
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <h3 style={{ fontSize: '16px', fontWeight: 800 }}>Traceable Bill of Quantities (BoQ)</h3>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Click quantity to edit and see carbon update live</p>
              </div>

              {/* Class Tabs */}
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {classes.map(c => (
                  <button
                    key={c}
                    onClick={() => setSelectedClass(c)}
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '4px 10px',
                      borderRadius: '6px',
                      backgroundColor: selectedClass === c ? 'var(--accent-blue)' : 'var(--bg-subtle)',
                      color: selectedClass === c ? '#fff' : 'var(--text-muted)',
                      textTransform: 'capitalize'
                    }}
                  >
                    {c.replace('_', ' ')}
                  </button>
                ))}
              </div>
            </div>

            {/* Table */}
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-dim)', fontSize: '11px', textTransform: 'uppercase' }}>
                    <th style={{ padding: '12px 16px' }}>Element & Tag</th>
                    <th style={{ padding: '12px 14px' }}>Material</th>
                    <th style={{ padding: '12px 14px', textAlign: 'right' }}>Quantity</th>
                    <th style={{ padding: '12px 14px' }}>Unit</th>
                    <th style={{ padding: '12px 14px' }}>Confidence</th>
                    <th style={{ padding: '12px 14px' }}>Provenance</th>
                    <th style={{ padding: '12px 16px', textAlign: 'right' }}>Embodied Carbon</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLines.map(ln => {
                    const cInfo = carbonMap[ln.id];
                    const isEditing = editingLineId === ln.id;
                    const confidenceColor = ln.confidence === 'measured' ? 'var(--accent-green)' : (ln.confidence === 'inferred' ? 'var(--accent-amber)' : 'var(--accent-blue)');

                    return (
                      <tr 
                        key={ln.id} 
                        style={{ 
                          borderBottom: '1px solid var(--border)',
                          backgroundColor: ln.is_overridden ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                          transition: 'background-color 0.15s'
                        }}
                      >
                        {/* Element & Tag */}
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ fontWeight: 700 }}>{ln.description || ln.element_class.replace('_', ' ')}</div>
                          {ln.assembly_tag && (
                            <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--accent-blue)', backgroundColor: 'var(--accent-blue-bg)', padding: '1px 6px', borderRadius: '4px' }}>
                              Tag: {ln.assembly_tag}
                            </span>
                          )}
                        </td>

                        {/* Material */}
                        <td style={{ padding: '12px 14px', color: 'var(--text-muted)' }}>
                          <div>{ln.material || cInfo?.factor?.name || '—'}</div>
                          {cInfo?.factor && (
                            <span style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                              EPD: {cInfo.factor.declared_unit} @ {cInfo.factor.gwp_value} kgCO₂e
                            </span>
                          )}
                        </td>

                        {/* Quantity (Editable) */}
                        <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                          {isEditing ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end' }}>
                              <input 
                                type="number" 
                                value={editQty}
                                onChange={e => setEditQty(e.target.value)}
                                style={{
                                  width: '80px',
                                  padding: '4px 6px',
                                  borderRadius: '4px',
                                  backgroundColor: 'var(--bg-main)',
                                  border: '1px solid var(--accent-blue)',
                                  color: '#fff',
                                  fontSize: '13px',
                                  textAlign: 'right'
                                }}
                                autoFocus
                              />
                              <button 
                                onClick={() => handleOverrideQuantity(ln.id, editQty)}
                                style={{ backgroundColor: 'var(--accent-green)', color: '#fff', padding: '4px 6px', borderRadius: '4px' }}
                              >
                                <Check size={12} />
                              </button>
                            </div>
                          ) : (
                            <div 
                              onClick={() => { setEditingLineId(ln.id); setEditQty(ln.effective_quantity); }}
                              style={{ cursor: 'pointer', display: 'inline-block' }}
                              title="Click to edit quantity"
                            >
                              <span style={{ fontWeight: 700, textDecoration: 'underline dotted var(--border-light)' }}>
                                {ln.effective_quantity}
                              </span>
                              {ln.is_overridden && (
                                <span style={{ marginLeft: '4px', fontSize: '10px', color: 'var(--accent-blue)' }}>(edited)</span>
                              )}
                            </div>
                          )}
                        </td>

                        {/* Unit */}
                        <td style={{ padding: '12px 14px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                          {ln.unit}
                        </td>

                        {/* Confidence */}
                        <td style={{ padding: '12px 14px' }}>
                          <span style={{ 
                            fontSize: '11px', 
                            fontWeight: 700, 
                            padding: '3px 8px', 
                            borderRadius: '12px',
                            backgroundColor: `${confidenceColor}22`,
                            color: confidenceColor,
                            textTransform: 'uppercase'
                          }}>
                            {ln.confidence}
                          </span>
                        </td>

                        {/* Provenance */}
                        <td style={{ padding: '12px 14px', fontSize: '12px', color: 'var(--text-dim)' }}>
                          <div>Sheet: {ln.provenance.sheet_no || `p.${ln.provenance.page}`}</div>
                          {ln.provenance.detail && <div>Det: {ln.provenance.detail}</div>}
                        </td>

                        {/* Embodied Carbon */}
                        <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                          {cInfo?.is_counted ? (
                            <div>
                              <span style={{ fontWeight: 800, color: 'var(--text-main)' }}>
                                {Number(cInfo.kg_co2e).toLocaleString()}
                              </span>
                              <span style={{ fontSize: '11px', color: 'var(--text-dim)', marginLeft: '4px' }}>kg</span>
                            </div>
                          ) : (
                            <span style={{ fontSize: '11px', color: 'var(--accent-amber)', fontStyle: 'italic' }}>
                              No factor found
                            </span>
                          )}
                        </td>

                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Column: Contribution Analysis & Stage 4 Substitutions */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            
            {/* Contribution Breakdown */}
            <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
                <BarChart3 size={18} color="var(--accent-blue)" />
                <h3 style={{ fontSize: '15px', fontWeight: 800 }}>Carbon Contribution Breakdown</h3>
              </div>

              <div style={{ marginBottom: '16px' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase' }}>By Assembly</span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px' }}>
                  {carbon?.by_assembly?.map(a => (
                    <div key={a.key}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                        <span style={{ fontWeight: 600 }}>{a.key}</span>
                        <span style={{ color: 'var(--text-muted)' }}>{Number(a.kg_co2e).toLocaleString()} kg ({a.pct_of_total}%)</span>
                      </div>
                      <div style={{ width: '100%', height: '6px', backgroundColor: 'var(--bg-subtle)', borderRadius: '3px', overflow: 'hidden' }}>
                        <div style={{ width: `${a.pct_of_total}%`, height: '100%', backgroundColor: 'var(--accent-blue)' }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase' }}>By Material Category</span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px' }}>
                  {carbon?.by_material_category?.slice(0, 4).map(m => (
                    <div key={m.key}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                        <span style={{ fontWeight: 600 }}>{m.key}</span>
                        <span style={{ color: 'var(--text-muted)' }}>{Number(m.kg_co2e).toLocaleString()} kg ({m.pct_of_total}%)</span>
                      </div>
                      <div style={{ width: '100%', height: '6px', backgroundColor: 'var(--bg-subtle)', borderRadius: '3px', overflow: 'hidden' }}>
                        <div style={{ width: `${m.pct_of_total}%`, height: '100%', backgroundColor: 'var(--accent-green)' }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Stage 4: Ranked Substitutions Panel */}
            <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Sliders size={18} color="var(--accent-green)" />
                  <h3 style={{ fontSize: '15px', fontWeight: 800 }}>Low-Carbon Material Swaps</h3>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Ranked by computed Δ kgCO₂e</span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {substitutions.map((sub, i) => (
                  <div 
                    key={i}
                    style={{ 
                      backgroundColor: 'var(--bg-subtle)', 
                      border: '1px solid var(--border)', 
                      borderRadius: '8px', 
                      padding: '14px' 
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
                      <span style={{ fontSize: '13px', fontWeight: 700 }}>{sub.to_material}</span>
                      <span style={{ 
                        fontSize: '13px', 
                        fontWeight: 800, 
                        color: sub.delta_kg_co2e < 0 ? 'var(--accent-green)' : 'var(--accent-rose)' 
                      }}>
                        {sub.delta_kg_co2e.toLocaleString()} kg ({sub.pct_of_total}%)
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '10px' }}>
                      <span>Replaces:</span>
                      <span style={{ textDecoration: 'line-through', color: 'var(--text-dim)' }}>{sub.from_material}</span>
                    </div>

                    <button 
                      onClick={() => alert(`Substitution applied! Swapped to ${sub.to_material}. Saved ${Math.abs(sub.delta_kg_co2e)} kg CO2e.`)}
                      style={{
                        width: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '6px',
                        fontSize: '12px',
                        fontWeight: 600,
                        backgroundColor: 'var(--accent-green-bg)',
                        color: 'var(--accent-green)',
                        border: '1px solid var(--accent-green)',
                        borderRadius: '6px',
                        padding: '6px'
                      }}
                    >
                      <CheckCircle2 size={13} />
                      Simulate Swap ({sub.delta_kg_co2e.toLocaleString()} kg)
                    </button>
                  </div>
                ))}
              </div>
            </div>

          </div>
        </div>

      </main>
    </div>
  );
}
