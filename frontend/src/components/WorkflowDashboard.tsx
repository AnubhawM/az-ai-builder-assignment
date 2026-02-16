// src/components/WorkflowDashboard.tsx
import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { toast } from 'react-toastify';

interface User {
    id: number;
    name: string;
    role: string;
    email: string;
}

interface WorkflowSummary {
    id: number;
    user_id: number;
    title: string;
    status: string;
    workflow_type: string;
    created_at: string;
    updated_at: string;
    owner: { name: string; role: string } | null;
    steps: Array<{ step_type: string; status: string; iteration_count: number }>;
}

interface InviteRequest {
    id: number;
    title: string;
    description: string;
    required_capabilities: string[];
    created_at: string;
    requester: { name: string; role: string } | null;
}

interface MarketplaceInvite {
    volunteer_id: number;
    request: InviteRequest;
}

interface WorkflowDashboardProps {
    currentUser: User;
    onSelectWorkflow: (workflowId: number) => void;
    onSelectRequest: (requestId: number) => void;
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

const runningWorkflowStatuses = new Set(['researching', 'refining', 'generating_ppt']);
const CENTRAL_TIME_ZONE = 'America/Chicago';

const WorkflowDashboard: React.FC<WorkflowDashboardProps> = ({ currentUser, onSelectWorkflow, onSelectRequest }) => {
    const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
    const [invites, setInvites] = useState<MarketplaceInvite[]>([]);
    const [loading, setLoading] = useState(true);
    const [deletingWorkflowId, setDeletingWorkflowId] = useState<number | null>(null);
    const [acceptingInviteId, setAcceptingInviteId] = useState<number | null>(null);

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

    const fetchInvites = useCallback(async () => {
        try {
            const res = await axios.get(`${import.meta.env.VITE_API_URL}/api/marketplace/invites`, {
                params: { user_id: currentUser.id }
            });
            setInvites(res.data.invites || []);
        } catch (err) {
            console.error('Failed to fetch marketplace invites:', err);
        }
    }, [currentUser.id]);

    useEffect(() => {
        fetchWorkflows();
        fetchInvites();
        // Poll for updates every 5 seconds
        const interval = setInterval(() => {
            fetchWorkflows();
            fetchInvites();
        }, 5000);
        return () => clearInterval(interval);
    }, [fetchInvites, fetchWorkflows]);

    const handleCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>, workflowId: number) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        onSelectWorkflow(workflowId);
    };

    const handleDeleteWorkflow = async (workflow: WorkflowSummary) => {
        if (deletingWorkflowId !== null) return;
        if (runningWorkflowStatuses.has(workflow.status)) {
            toast.error('Cancel the active run before deleting this workflow.');
            return;
        }
        const confirmed = window.confirm(
            `Delete "${workflow.title}"? This action cannot be undone.`
        );
        if (!confirmed) return;

        setDeletingWorkflowId(workflow.id);
        try {
            await axios.delete(`${import.meta.env.VITE_API_URL}/api/workflows/${workflow.id}`, {
                data: { user_id: currentUser.id }
            });
            setWorkflows((prev) => prev.filter((item) => item.id !== workflow.id));
            toast.success('Workflow deleted.');
        } catch (err) {
            const errorMsg = axios.isAxiosError(err)
                ? err.response?.data?.error || 'Failed to delete workflow.'
                : 'Failed to delete workflow.';
            toast.error(errorMsg);
            console.error('Failed to delete workflow:', err);
        } finally {
            setDeletingWorkflowId(null);
        }
    };

    const handleAcceptInvite = async (invite: MarketplaceInvite) => {
        if (acceptingInviteId !== null) return;
        setAcceptingInviteId(invite.volunteer_id);
        try {
            const res = await axios.post(
                `${import.meta.env.VITE_API_URL}/api/marketplace/${invite.request.id}/accept`,
                {
                    volunteer_id: invite.volunteer_id,
                    user_id: currentUser.id
                }
            );
            toast.success('Collaboration started.');
            setInvites((prev) => prev.filter((item) => item.volunteer_id !== invite.volunteer_id));
            onSelectWorkflow(res.data.workflow_id);
        } catch (err) {
            const errorMsg = axios.isAxiosError(err)
                ? err.response?.data?.error || 'Failed to accept request.'
                : 'Failed to accept request.';
            toast.error(errorMsg);
        } finally {
            setAcceptingInviteId(null);
        }
    };

    const formatDate = (dateStr: string) => {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            timeZone: CENTRAL_TIME_ZONE,
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
        <div className="max-w-5xl mx-auto px-6 py-8">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h2 className="text-2xl font-bold text-white">Workflow Dashboard</h2>
                    <p className="text-[var(--color-text-secondary)] text-sm mt-1">
                        Manage research and presentation workflows
                    </p>
                </div>
            </div>
            {/* Pending Collaboration Requests */}
            <section className="mb-8">
                <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider mb-3">
                    Pending Collaboration Requests ({invites.length})
                </h3>
                {invites.length === 0 ? (
                    <div className="glass-card-static p-6 text-center">
                        <p className="text-[var(--color-text-muted)] text-sm">No direct invites right now.</p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {invites.map((invite) => (
                            <div
                                key={invite.volunteer_id}
                                onClick={() => onSelectRequest(invite.request.id)}
                                onKeyDown={(event) => {
                                    if (event.key !== 'Enter' && event.key !== ' ') return;
                                    event.preventDefault();
                                    onSelectRequest(invite.request.id);
                                }}
                                role="button"
                                tabIndex={0}
                                className="glass-card-static p-5 flex flex-col sm:flex-row sm:items-center gap-4"
                            >
                                <div className="flex-1 min-w-0">
                                    <p className="text-xs text-purple-300 uppercase tracking-wider mb-1">
                                        Invited by {invite.request.requester?.name || 'Requester'}
                                    </p>
                                    <h4 className="text-white font-medium truncate">{invite.request.title}</h4>
                                    <p className="text-xs text-[var(--color-text-muted)] mt-1 line-clamp-2">
                                        {invite.request.description}
                                    </p>
                                    <div className="flex flex-wrap gap-2 mt-2">
                                        {invite.request.required_capabilities.slice(0, 4).map((cap) => (
                                            <span
                                                key={cap}
                                                className="bg-[var(--color-surface)] border border-[var(--color-border)] px-2 py-0.5 rounded text-[10px] text-[var(--color-text-secondary)] uppercase"
                                            >
                                                {cap}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                                <div className="flex items-center gap-3 sm:flex-col sm:items-end">
                                    <p className="text-xs text-[var(--color-text-muted)]">
                                        {formatDate(invite.request.created_at)}
                                    </p>
                                    <button
                                        onClick={(event) => {
                                            event.stopPropagation();
                                            void handleAcceptInvite(invite);
                                        }}
                                        onKeyDown={(event) => event.stopPropagation()}
                                        disabled={acceptingInviteId === invite.volunteer_id}
                                        className="btn btn-primary px-4 py-2 text-xs"
                                        id={`accept-invite-btn-${invite.volunteer_id}`}
                                    >
                                        {acceptingInviteId === invite.volunteer_id ? 'Starting...' : 'Accept & Start'}
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            {/* Active Workflows */}
            <section className="mb-8">
                <h3 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider mb-3">
                    Active Workflows ({activeWorkflows.length})
                </h3>
                {activeWorkflows.length === 0 ? (
                    <div className="glass-card-static p-8 text-center">
                        <p className="text-[var(--color-text-muted)]">
                            No workflows awaiting your input.
                        </p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {activeWorkflows.map((w) => {
                            const status = statusConfig[w.status] || statusConfig.pending;
                            return (
                                <div
                                    key={w.id}
                                    onClick={() => onSelectWorkflow(w.id)}
                                    onKeyDown={(e) => handleCardKeyDown(e, w.id)}
                                    role="button"
                                    tabIndex={0}
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

                                    {/* Meta + Actions */}
                                    <div className="flex items-center gap-3 flex-shrink-0">
                                        <div className="text-right hidden sm:block">
                                            <p className="text-xs text-[var(--color-text-muted)]">
                                                {w.owner?.name || 'Unknown'}
                                            </p>
                                            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                                                {formatDate(w.updated_at || w.created_at)}
                                            </p>
                                        </div>
                                        {w.user_id === currentUser.id && (
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    void handleDeleteWorkflow(w);
                                                }}
                                                onKeyDown={(e) => e.stopPropagation()}
                                                disabled={deletingWorkflowId === w.id}
                                                className="btn btn-ghost text-xs px-3 py-1.5 text-red-300"
                                                id={`delete-workflow-btn-${w.id}`}
                                            >
                                                {deletingWorkflowId === w.id ? 'Deleting...' : 'Delete'}
                                            </button>
                                        )}
                                    </div>

                                    {/* Arrow */}
                                    <span className="text-[var(--color-text-muted)] text-lg flex-shrink-0">›</span>
                                </div>
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
                                <div
                                    key={w.id}
                                    onClick={() => onSelectWorkflow(w.id)}
                                    onKeyDown={(e) => handleCardKeyDown(e, w.id)}
                                    role="button"
                                    tabIndex={0}
                                    className="glass-card-static w-full p-4 text-left flex items-center gap-4 cursor-pointer"
                                >
                                    <div className="text-xl flex-shrink-0">{status.icon}</div>
                                    <div className="flex-1 min-w-0">
                                        <h4 className="text-white font-medium truncate text-sm">{w.title}</h4>
                                    </div>
                                    <span className={`badge ${status.badge}`}>{status.label}</span>
                                    <p className="text-xs text-[var(--color-text-muted)] flex-shrink-0 hidden sm:block">
                                        {formatDate(w.created_at)}
                                    </p>
                                    {w.user_id === currentUser.id && (
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                void handleDeleteWorkflow(w);
                                            }}
                                            onKeyDown={(e) => e.stopPropagation()}
                                            disabled={deletingWorkflowId === w.id}
                                            className="btn btn-ghost text-xs px-3 py-1.5 text-red-300"
                                            id={`delete-workflow-btn-${w.id}`}
                                        >
                                            {deletingWorkflowId === w.id ? 'Deleting...' : 'Delete'}
                                        </button>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>
        </div>
    );
};

export default WorkflowDashboard;
