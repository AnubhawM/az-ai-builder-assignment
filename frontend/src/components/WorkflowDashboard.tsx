// src/components/WorkflowDashboard.tsx
import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';

interface User {
    id: number;
    name: string;
    role: string;
    email: string;
}

interface WorkflowSummary {
    id: number;
    title: string;
    status: string;
    workflow_type: string;
    created_at: string;
    updated_at: string;
    owner: { name: string; role: string } | null;
    steps: Array<{ step_type: string; status: string; iteration_count: number }>;
}

interface WorkflowDashboardProps {
    currentUser: User;
    onSelectWorkflow: (workflowId: number) => void;
}

const statusConfig: Record<string, { label: string; badge: string; icon: string }> = {
    pending: { label: 'Pending', badge: 'badge-pending', icon: '⏳' },
    collaborating: { label: 'Collaborating', badge: 'badge-active', icon: '💬' },
    researching: { label: 'Research In Progress', badge: 'badge-active', icon: '🔍' },
    refining: { label: 'Refining Research', badge: 'badge-active', icon: '🔄' },
    awaiting_review: { label: 'Awaiting Review', badge: 'badge-review', icon: '👁️' },
    generating_ppt: { label: 'Generating PPT', badge: 'badge-active', icon: '📊' },
    completed: { label: 'Completed', badge: 'badge-success', icon: '✅' },
    failed: { label: 'Failed', badge: 'badge-error', icon: '❌' },
};

const WorkflowDashboard: React.FC<WorkflowDashboardProps> = ({ currentUser, onSelectWorkflow }) => {
    const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [showNewForm, setShowNewForm] = useState(false);
    const [newTopic, setNewTopic] = useState('');
    const [creating, setCreating] = useState(false);

    const fetchWorkflows = useCallback(async () => {
        try {
            const res = await axios.get(`${import.meta.env.VITE_API_URL}/api/workflows`, {
                params: { user_id: currentUser.id }
            });
            setWorkflows(res.data.workflows);
        } catch (err) {
            console.error('Failed to fetch workflows:', err);
        } finally {
            setLoading(false);
        }
    }, [currentUser.id]);

    useEffect(() => {
        fetchWorkflows();
        // Poll for updates every 5 seconds
        const interval = setInterval(fetchWorkflows, 5000);
        return () => clearInterval(interval);
    }, [fetchWorkflows]);

    const handleCreateWorkflow = async () => {
        if (!newTopic.trim() || creating) return;
        setCreating(true);
        try {
            const res = await axios.post(`${import.meta.env.VITE_API_URL}/api/workflows`, {
                topic: newTopic.trim(),
                user_id: currentUser.id,
                workflow_type: 'ppt_generation',
            });
            setNewTopic('');
            setShowNewForm(false);
            // Navigate to the newly created workflow
            onSelectWorkflow(res.data.workflow.id);
        } catch (err) {
            console.error('Failed to create workflow:', err);
        } finally {
            setCreating(false);
        }
    };

    const formatDate = (dateStr: string) => {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
    };

    // Categorize workflows
    const activeWorkflows = workflows.filter(w =>
        !['completed', 'failed'].includes(w.status)
    );
    const completedWorkflows = workflows.filter(w =>
        ['completed', 'failed'].includes(w.status)
    );

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <div className="text-center">
                    <div className="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin-slow mx-auto mb-4" />
                    <p className="text-[var(--color-text-secondary)]">Loading workflows...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto px-6 py-8 animate-fade-in">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h2 className="text-2xl font-bold text-white">Workflow Dashboard</h2>
                    <p className="text-[var(--color-text-secondary)] text-sm mt-1">
                        Manage research and presentation workflows
                    </p>
                </div>
                {currentUser.role === 'researcher' && (
                    <button
                        onClick={() => setShowNewForm(!showNewForm)}
                        className="btn btn-primary"
                        id="new-workflow-btn"
                    >
                        <span>+</span> New Request
                    </button>
                )}
            </div>

            {/* New Workflow Form */}
            {showNewForm && (
                <div className="glass-card p-6 mb-6 animate-fade-in">
                    <h3 className="text-white font-semibold mb-3">Create New Research Workflow</h3>
                    <div className="flex gap-3">
                        <input
                            type="text"
                            value={newTopic}
                            onChange={(e) => setNewTopic(e.target.value)}
                            placeholder="Enter a research topic (e.g., Sustainable energy technologies for AZ manufacturing)"
                            className="flex-1 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-4 py-3 text-white text-sm placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-purple-500 transition-colors"
                            onKeyDown={(e) => e.key === 'Enter' && handleCreateWorkflow()}
                            disabled={creating}
                            id="new-workflow-topic"
                        />
                        <button
                            onClick={handleCreateWorkflow}
                            disabled={!newTopic.trim() || creating}
                            className="btn btn-primary whitespace-nowrap"
                            id="submit-workflow-btn"
                        >
                            {creating ? (
                                <>
                                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin-slow" />
                                    Starting...
                                </>
                            ) : (
                                'Start Research'
                            )}
                        </button>
                    </div>
                    <p className="text-[var(--color-text-muted)] text-xs mt-2">
                        OpenClaw will research the topic and produce an executive summary and slide outline for your review.
                    </p>
                </div>
            )}

            {/* Active Workflows */}
            <section className="mb-8">
                <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider mb-3">
                    Active Workflows ({activeWorkflows.length})
                </h3>
                {activeWorkflows.length === 0 ? (
                    <div className="glass-card-static p-8 text-center">
                        <p className="text-[var(--color-text-muted)]">
                            {currentUser.role === 'researcher'
                                ? 'No active workflows. Click "New Request" to start one.'
                                : 'No workflows awaiting your input.'}
                        </p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {activeWorkflows.map((w) => {
                            const status = statusConfig[w.status] || statusConfig.pending;
                            return (
                                <button
                                    key={w.id}
                                    onClick={() => onSelectWorkflow(w.id)}
                                    className="glass-card w-full p-5 text-left flex items-center gap-4 cursor-pointer"
                                    id={`workflow-card-${w.id}`}
                                >
                                    {/* Status icon */}
                                    <div className="text-2xl flex-shrink-0">{status.icon}</div>

                                    {/* Content */}
                                    <div className="flex-1 min-w-0">
                                        <h4 className="text-white font-medium truncate">{w.title}</h4>
                                        <div className="flex items-center gap-3 mt-1">
                                            <span className={`badge ${status.badge}`}>{status.label}</span>
                                            {w.steps.some(s => s.iteration_count > 0) && (
                                                <span className="text-xs text-[var(--color-text-muted)]">
                                                    Round {Math.max(...w.steps.map(s => s.iteration_count))}
                                                </span>
                                            )}
                                        </div>
                                    </div>

                                    {/* Meta */}
                                    <div className="text-right flex-shrink-0 hidden sm:block">
                                        <p className="text-xs text-[var(--color-text-muted)]">
                                            {w.owner?.name || 'Unknown'}
                                        </p>
                                        <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                                            {formatDate(w.updated_at || w.created_at)}
                                        </p>
                                    </div>

                                    {/* Arrow */}
                                    <span className="text-[var(--color-text-muted)] text-lg flex-shrink-0">›</span>
                                </button>
                            );
                        })}
                    </div>
                )}
            </section>

            {/* Completed Workflows */}
            <section>
                <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider mb-3">
                    Completed ({completedWorkflows.length})
                </h3>
                {completedWorkflows.length === 0 ? (
                    <div className="glass-card-static p-6 text-center">
                        <p className="text-[var(--color-text-muted)] text-sm">No completed workflows yet.</p>
                    </div>
                ) : (
                    <div className="space-y-2">
                        {completedWorkflows.map((w) => {
                            const status = statusConfig[w.status] || statusConfig.pending;
                            return (
                                <button
                                    key={w.id}
                                    onClick={() => onSelectWorkflow(w.id)}
                                    className="glass-card-static w-full p-4 text-left flex items-center gap-4 cursor-pointer opacity-80 hover:opacity-100 transition-opacity"
                                >
                                    <div className="text-xl flex-shrink-0">{status.icon}</div>
                                    <div className="flex-1 min-w-0">
                                        <h4 className="text-white font-medium truncate text-sm">{w.title}</h4>
                                    </div>
                                    <span className={`badge ${status.badge}`}>{status.label}</span>
                                    <p className="text-xs text-[var(--color-text-muted)] flex-shrink-0 hidden sm:block">
                                        {formatDate(w.created_at)}
                                    </p>
                                </button>
                            );
                        })}
                    </div>
                )}
            </section>
        </div>
    );
};

export default WorkflowDashboard;
