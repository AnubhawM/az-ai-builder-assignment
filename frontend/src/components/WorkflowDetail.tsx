import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';

interface User {
    id: number;
    name: string;
    role: string;
    email: string;
    is_agent?: boolean;
}

interface WorkflowStep {
    id: number;
    step_order: number;
    step_type: string;
    status: string;
    provider_type: string;
    assigned_to: number | null;
    assignee: User | null;
    input_data: Record<string, any> | null;
    output_data: Record<string, any> | null;
    feedback: string | null;
    iteration_count: number;
    created_at: string;
    updated_at: string;
}

interface WorkflowEvent {
    id: number;
    event_type: string;
    actor_type: string;
    actor_id: number | null;
    actor: User | null;
    channel: string | null;
    message: string | null;
    created_at: string;
}

interface WorkflowMessage {
    id: number;
    sender_id: number | null;
    sender_type: string;
    channel: string;
    message: string;
    created_at: string;
    sender: User | null;
}

interface WorkflowApproval {
    id: number;
    user_id: number;
    status: 'pending' | 'ready' | 'approved';
    user: User | null;
}

interface Workflow {
    id: number;
    user_id: number;
    title: string;
    status: string;
    workflow_type: string;
    openclaw_session_id: string | null;
    owner: User | null;
    steps: WorkflowStep[];
    events: WorkflowEvent[];
    messages: WorkflowMessage[];
    approvals: WorkflowApproval[];
    created_at: string;
    updated_at: string;
}

interface WorkflowDetailProps {
    workflowId: number;
    currentUser: User;
    onBack: () => void;
}

const stepTypeLabels: Record<string, { label: string; icon: string }> = {
    agent_research: { label: 'Research', icon: '🔬' },
    human_review: { label: 'Review', icon: '👁️' },
    specialist_review: { label: 'Specialist', icon: '🧠' },
    human_research: { label: 'Human Work', icon: '🧾' },
    agent_collaboration: { label: 'Agent Collab', icon: '🤖' },
    agent_generation: { label: 'Generate', icon: '📊' },
    presentation_review: { label: 'PPT Review', icon: '🎨' },
};

const stepStatusToClass: Record<string, string> = {
    pending: 'pipeline-dot-pending',
    in_progress: 'pipeline-dot-active',
    awaiting_input: 'pipeline-dot-active',
    completed: 'pipeline-dot-completed',
    failed: 'pipeline-dot-failed',
    skipped: 'pipeline-dot-pending',
};

const eventIcons: Record<string, string> = {
    created: '🚀',
    research_started: '🔍',
    research_completed: '✅',
    review_requested: '📋',
    approved: '👍',
    refined: '🔄',
    generation_requested: '📝',
    generation_started: '⚙️',
    generation_completed: '🎉',
    message_posted: '💬',
    completion_marked: '✅',
    reopened: '↩️',
    agent_replied: '🤖',
    notification_sent: '📨',
    failed: '❌',
};

const workflowStatusLabel: Record<string, string> = {
    pending: 'Pending',
    researching: 'Researching',
    refining: 'Refining',
    awaiting_review: 'Awaiting Review',
    generating_ppt: 'Generating PPT',
    collaborating: 'Collaborating',
    completed: 'Completed',
    failed: 'Failed',
};

const WorkflowDetail: React.FC<WorkflowDetailProps> = ({ workflowId, currentUser, onBack }) => {
    const [workflow, setWorkflow] = useState<Workflow | null>(null);
    const [loading, setLoading] = useState(true);
    const [feedback, setFeedback] = useState('');
    const [chatInput, setChatInput] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [sendingMessage, setSendingMessage] = useState(false);
    const [updatingCompletion, setUpdatingCompletion] = useState(false);
    const [triggeringResearch, setTriggeringResearch] = useState(false);
    const [triggeringGeneration, setTriggeringGeneration] = useState(false);
    const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
        summary: true,
        outline: true,
        raw: false,
    });

    const fetchWorkflow = useCallback(async () => {
        try {
            const res = await axios.get(`${import.meta.env.VITE_API_URL}/api/workflows/${workflowId}`, {
                params: { user_id: currentUser.id }
            });
            setWorkflow(res.data.workflow);
        } catch (err) {
            console.error('Failed to fetch workflow:', err);
        } finally {
            setLoading(false);
        }
    }, [workflowId, currentUser.id]);

    useEffect(() => {
        fetchWorkflow();
        const interval = setInterval(fetchWorkflow, 3000);
        return () => clearInterval(interval);
    }, [fetchWorkflow]);

    const handleReview = async (action: 'approve' | 'refine') => {
        if (submitting) return;
        if (action === 'refine' && !feedback.trim()) return;

        setSubmitting(true);
        try {
            await axios.post(`${import.meta.env.VITE_API_URL}/api/workflows/${workflowId}/review`, {
                action,
                feedback: action === 'refine' ? feedback.trim() : undefined,
                user_id: currentUser.id,
                channel: 'web',
            });
            setFeedback('');
            fetchWorkflow();
        } catch (err: any) {
            console.error('Review action failed:', err);
            alert(err.response?.data?.error || 'Failed to submit review');
        } finally {
            setSubmitting(false);
        }
    };

    const handleSendMessage = async () => {
        if (sendingMessage) return;
        if (!chatInput.trim()) return;

        setSendingMessage(true);
        try {
            await axios.post(`${import.meta.env.VITE_API_URL}/api/workflows/${workflowId}/messages`, {
                user_id: currentUser.id,
                message: chatInput.trim(),
                channel: 'web'
            });
            setChatInput('');
            fetchWorkflow();
        } catch (err: any) {
            console.error('Failed to send workflow message:', err);
            alert(err.response?.data?.error || 'Failed to send message');
        } finally {
            setSendingMessage(false);
        }
    };

    const handleCompletion = async (action: 'mark_ready' | 'reopen') => {
        if (updatingCompletion) return;
        setUpdatingCompletion(true);
        try {
            await axios.post(`${import.meta.env.VITE_API_URL}/api/workflows/${workflowId}/completion`, {
                user_id: currentUser.id,
                action
            });
            fetchWorkflow();
        } catch (err: any) {
            console.error('Failed to update completion state:', err);
            alert(err.response?.data?.error || 'Failed to update completion state');
        } finally {
            setUpdatingCompletion(false);
        }
    };

    const handleStartResearch = async () => {
        if (triggeringResearch) return;
        setTriggeringResearch(true);
        try {
            await axios.post(`${import.meta.env.VITE_API_URL}/api/workflows/${workflowId}/start-research`, {
                user_id: currentUser.id
            });
            fetchWorkflow();
        } catch (err: any) {
            console.error('Failed to start research from collaboration:', err);
            alert(err.response?.data?.error || 'Failed to start research');
        } finally {
            setTriggeringResearch(false);
        }
    };

    const handleGenerateFromChat = async () => {
        if (triggeringGeneration) return;
        setTriggeringGeneration(true);
        try {
            await axios.post(`${import.meta.env.VITE_API_URL}/api/workflows/${workflowId}/generate-ppt`, {
                user_id: currentUser.id,
                instructions: chatInput.trim() || undefined
            });
            fetchWorkflow();
        } catch (err: any) {
            console.error('Failed to trigger generation from chat:', err);
            alert(err.response?.data?.error || 'Failed to trigger PPT generation');
        } finally {
            setTriggeringGeneration(false);
        }
    };

    const toggleSection = (key: string) => {
        setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const formatTime = (dateStr: string) => {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    };

    const formatDate = (dateStr: string) => {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    };

    if (loading || !workflow) {
        return (
            <div className="flex items-center justify-center py-20">
                <div className="text-center">
                    <div className="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin-slow mx-auto mb-4" />
                    <p className="text-[var(--color-text-secondary)]">Loading workflow...</p>
                </div>
            </div>
        );
    }

    const orderedSteps = [...workflow.steps].sort((a, b) => a.step_order - b.step_order);
    const pipelineSteps = orderedSteps.length > 0
        ? orderedSteps.slice(0, 4).map((step) => {
            const fallbackLabel = step.step_type.replace(/_/g, ' ');
            const labelInfo = stepTypeLabels[step.step_type] || { label: fallbackLabel, icon: '📌' };
            return {
                key: `step-${step.id}`,
                ...labelInfo,
                step,
            };
        })
        : [
            { key: 'pending', label: 'Pending', icon: '⏳', step: null }
        ];

    const researchStep = workflow.steps.find(s => s.step_type === 'agent_research');
    const researchOutput = researchStep?.output_data;
    const generationStep = workflow.steps
        .filter(s => s.step_type === 'agent_generation')
        .slice(-1)[0];

    const isAwaitingReview = workflow.status === 'awaiting_review';
    const isProcessing = ['researching', 'refining', 'generating_ppt', 'pending'].includes(workflow.status);
    const hasAgentParticipant = workflow.steps.some(
        s => s.assignee?.is_agent || s.provider_type === 'agent'
    );
    const requiresResearch = workflow.steps.some(
        s => Boolean(s.input_data?.requires_research)
    );
    const canStartResearch = workflow.status === 'collaborating'
        && hasAgentParticipant
        && requiresResearch
        && !researchStep
        && currentUser.id === workflow.user_id;

    const humanApprovals = workflow.approvals.filter(a => !a.user?.is_agent);
    const currentApproval = humanApprovals.find(a => a.user_id === currentUser.id);
    const isCurrentUserReady = currentApproval?.status === 'ready' || currentApproval?.status === 'approved';
    const canUseCompletion = humanApprovals.length >= 2 && humanApprovals.some(a => a.user_id === currentUser.id);

    return (
        <div className="max-w-6xl mx-auto px-6 py-8 animate-fade-in">
            <div className="flex items-center gap-4 mb-6">
                <button onClick={onBack} className="btn btn-ghost text-sm" id="back-btn">
                    ← Dashboard
                </button>
                <div className="flex-1">
                    <h2 className="text-xl font-bold text-white truncate">{workflow.title}</h2>
                    <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                        Created by {workflow.owner?.name} · {formatDate(workflow.created_at)}
                        <span className="ml-2 text-purple-400">· {workflowStatusLabel[workflow.status] || workflow.status}</span>
                        {researchStep && researchStep.iteration_count > 0 && (
                            <span className="ml-2 text-purple-400">· Refinement round {researchStep.iteration_count}</span>
                        )}
                    </p>
                </div>
            </div>

            <div className="glass-card-static p-6 mb-6">
                <div className="flex items-start justify-between">
                    {pipelineSteps.map((ps, idx) => {
                        const step = ps.step;
                        const status = step ? step.status : 'pending';
                        const dotClass = stepStatusToClass[status] || 'pipeline-dot-pending';
                        const isLast = idx === pipelineSteps.length - 1;
                        const prevCompleted = idx > 0 && pipelineSteps[idx - 1].step?.status === 'completed';

                        return (
                            <div key={ps.key} className="pipeline-step">
                                {!isLast && (
                                    <div className={`pipeline-connector ${prevCompleted || status === 'completed' ? 'pipeline-connector-completed' : ''}`} />
                                )}
                                <div className={`pipeline-dot ${dotClass}`}>
                                    {status === 'completed' ? '✓' : ps.icon}
                                </div>
                                <p className="text-xs font-medium text-[var(--color-text-secondary)] mt-2 text-center">
                                    {ps.label}
                                </p>
                                {status === 'in_progress' && (
                                    <p className="text-[10px] text-purple-400 mt-0.5">In Progress</p>
                                )}
                                {status === 'awaiting_input' && (
                                    <p className="text-[10px] text-purple-400 mt-0.5">Awaiting Input</p>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-4">
                    {isProcessing && !researchOutput && workflow.status !== 'collaborating' && (
                        <div className="glass-card p-8 text-center">
                            <div className="w-12 h-12 border-2 border-purple-500 border-t-transparent rounded-full animate-spin-slow mx-auto mb-4" />
                            <h3 className="text-white font-semibold mb-2">
                                {workflow.status === 'researching' || workflow.status === 'pending'
                                    ? 'OpenClaw is Researching...'
                                    : workflow.status === 'refining'
                                        ? 'OpenClaw is Refining Research...'
                                        : 'Generating PowerPoint...'}
                            </h3>
                            <p className="text-[var(--color-text-secondary)] text-sm">
                                This may take a few minutes. The page will update automatically.
                            </p>
                        </div>
                    )}

                    {workflow.status === 'collaborating' && (
                        <div className="glass-card p-6 border-purple-500/30">
                            <h3 className="text-white font-semibold mb-2">Collaboration Active</h3>
                            <p className="text-sm text-[var(--color-text-secondary)]">
                                Use the workflow chat below to iterate with your collaborator.
                            </p>
                        </div>
                    )}

                    {researchOutput?.summary && (
                        <div className="glass-card p-6">
                            <button
                                onClick={() => toggleSection('summary')}
                                className="w-full flex items-center justify-between text-left"
                            >
                                <h3 className="text-white font-semibold flex items-center gap-2">
                                    📋 Executive Summary
                                </h3>
                                <span className="text-[var(--color-text-muted)]">
                                    {expandedSections.summary ? '▼' : '▶'}
                                </span>
                            </button>
                            {expandedSections.summary && (
                                <div className="mt-4 text-[var(--color-text-secondary)] text-sm leading-relaxed whitespace-pre-wrap">
                                    {researchOutput.summary}
                                </div>
                            )}
                        </div>
                    )}

                    {researchOutput?.slide_outline && (
                        <div className="glass-card p-6">
                            <button
                                onClick={() => toggleSection('outline')}
                                className="w-full flex items-center justify-between text-left"
                            >
                                <h3 className="text-white font-semibold flex items-center gap-2">
                                    📑 Slide Outline
                                </h3>
                                <span className="text-[var(--color-text-muted)]">
                                    {expandedSections.outline ? '▼' : '▶'}
                                </span>
                            </button>
                            {expandedSections.outline && (
                                <div className="mt-4 text-[var(--color-text-secondary)] text-sm leading-relaxed whitespace-pre-wrap font-mono">
                                    {researchOutput.slide_outline}
                                </div>
                            )}
                        </div>
                    )}

                    {researchOutput?.raw_research && (
                        <div className="glass-card p-6">
                            <button
                                onClick={() => toggleSection('raw')}
                                className="w-full flex items-center justify-between text-left"
                            >
                                <h3 className="text-white font-semibold flex items-center gap-2">
                                    🔬 Raw Research Data
                                </h3>
                                <span className="text-xs text-[var(--color-text-muted)] mr-2">
                                    {expandedSections.raw ? 'Collapse' : 'Expand'}
                                </span>
                                <span className="text-[var(--color-text-muted)]">
                                    {expandedSections.raw ? '▼' : '▶'}
                                </span>
                            </button>
                            {expandedSections.raw && (
                                <div className="mt-4 text-[var(--color-text-secondary)] text-sm leading-relaxed whitespace-pre-wrap max-h-[500px] overflow-y-auto">
                                    {researchOutput.raw_research}
                                </div>
                            )}
                        </div>
                    )}

                    {generationStep?.status === 'completed' && generationStep.output_data && (
                        <div className="glass-card p-6 border-green-500/30">
                            <h3 className="text-white font-semibold flex items-center gap-2 mb-3">
                                🎉 PowerPoint Generated
                            </h3>
                            <div className="flex items-center gap-4 bg-[var(--color-surface)] rounded-lg p-4">
                                <div className="text-3xl">📊</div>
                                <div className="flex-1">
                                    <p className="text-white font-medium">
                                        {generationStep.output_data.file_name}
                                    </p>
                                    <p className="text-xs text-[var(--color-text-muted)]">
                                        {generationStep.output_data.file_size_formatted || 'Ready for download'}
                                    </p>
                                </div>
                            </div>
                        </div>
                    )}

                    {workflow.status === 'generating_ppt' && (
                        <div className="glass-card p-8 text-center">
                            <div className="w-12 h-12 border-2 border-purple-500 border-t-transparent rounded-full animate-spin-slow mx-auto mb-4" />
                            <h3 className="text-white font-semibold mb-2">Generating PowerPoint...</h3>
                            <p className="text-[var(--color-text-secondary)] text-sm">
                                SlideSpeak is creating your presentation. This may take a few minutes.
                            </p>
                        </div>
                    )}

                    {isAwaitingReview && (
                        <div className="glass-card p-6 border-purple-500/30" id="review-panel">
                            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                                ⚡ Quality Gate — Your Review
                            </h3>

                            <div className="flex gap-3 mb-4">
                                <button
                                    onClick={() => handleReview('approve')}
                                    disabled={submitting}
                                    className="btn btn-success flex-1"
                                    id="approve-btn"
                                >
                                    {submitting ? 'Processing...' : '✅ Approve & Generate PPT'}
                                </button>
                            </div>

                            <div className="border-t border-[var(--color-border)] pt-4">
                                <label className="text-sm text-[var(--color-text-secondary)] font-medium mb-2 block">
                                    Or request refinements:
                                </label>
                                <textarea
                                    value={feedback}
                                    onChange={(e) => setFeedback(e.target.value)}
                                    placeholder="e.g., Please add more data about cost analysis and include recent statistics..."
                                    className="w-full bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-4 py-3 text-white text-sm placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-purple-500 transition-colors resize-none"
                                    rows={3}
                                    disabled={submitting}
                                    id="feedback-input"
                                />
                                <button
                                    onClick={() => handleReview('refine')}
                                    disabled={!feedback.trim() || submitting}
                                    className="btn btn-outline mt-2 w-full"
                                    id="refine-btn"
                                >
                                    {submitting ? 'Processing...' : '🔄 Request Refinement'}
                                </button>
                            </div>
                        </div>
                    )}

                    <div className="glass-card p-6" id="chat-panel">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-white font-semibold">💬 Collaboration Chat</h3>
                            {hasAgentParticipant && (
                                <span className="text-[10px] text-emerald-400 uppercase tracking-wider">
                                    OpenClaw enabled
                                </span>
                            )}
                        </div>

                        <div className="max-h-[340px] overflow-y-auto space-y-3 pr-1">
                            {workflow.messages.length === 0 ? (
                                <p className="text-sm text-[var(--color-text-muted)]">No messages yet.</p>
                            ) : (
                                workflow.messages.map((msg) => {
                                    const isOwn = msg.sender_id === currentUser.id;
                                    const senderName = msg.sender?.name
                                        || (msg.sender_type === 'agent' ? 'OpenClaw AI' : msg.sender_type === 'system' ? 'System' : 'Collaborator');
                                    return (
                                        <div
                                            key={msg.id}
                                            className={`rounded-lg p-3 border ${isOwn
                                                ? 'bg-purple-500/10 border-purple-500/30 ml-8'
                                                : msg.sender_type === 'agent'
                                                    ? 'bg-emerald-500/10 border-emerald-500/30 mr-8'
                                                    : 'bg-[var(--color-surface)] border-[var(--color-border)] mr-8'
                                                }`}
                                        >
                                            <div className="flex items-center justify-between mb-1">
                                                <span className="text-xs font-semibold text-white">{senderName}</span>
                                                <span className="text-[10px] text-[var(--color-text-muted)]">
                                                    {formatTime(msg.created_at)}
                                                </span>
                                            </div>
                                            <p className="text-sm text-[var(--color-text-secondary)] whitespace-pre-wrap">
                                                {msg.message}
                                            </p>
                                        </div>
                                    );
                                })
                            )}
                        </div>

                        <div className="mt-4 flex gap-2">
                            <textarea
                                value={chatInput}
                                onChange={(e) => setChatInput(e.target.value)}
                                placeholder="Write a message for your collaborator..."
                                rows={2}
                                className="flex-1 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-4 py-2 text-white text-sm placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-purple-500 transition-colors resize-none"
                                disabled={sendingMessage}
                            />
                            <button
                                onClick={handleSendMessage}
                                disabled={sendingMessage || !chatInput.trim()}
                                className="btn btn-primary h-fit"
                            >
                                {sendingMessage ? 'Sending...' : 'Send'}
                            </button>
                        </div>

                        {canStartResearch && (
                            <button
                                onClick={handleStartResearch}
                                disabled={triggeringResearch || workflow.status === 'generating_ppt'}
                                className="btn btn-success mt-3 w-full"
                            >
                                {triggeringResearch ? 'Starting...' : 'Start Agent Research'}
                            </button>
                        )}

                        {hasAgentParticipant && (
                            <button
                                onClick={handleGenerateFromChat}
                                disabled={triggeringGeneration || workflow.status === 'generating_ppt'}
                                className="btn btn-outline mt-3 w-full"
                            >
                                {triggeringGeneration ? 'Starting...' : '📊 Generate PPT From Chat Context'}
                            </button>
                        )}
                    </div>

                    {canUseCompletion && (
                        <div className="glass-card p-6 border-emerald-500/30">
                            <h3 className="text-white font-semibold mb-3">✅ Collaboration Completion</h3>
                            <div className="space-y-2 mb-4">
                                {humanApprovals.map((approval) => (
                                    <div key={approval.id} className="flex items-center justify-between text-sm">
                                        <span className="text-[var(--color-text-secondary)]">{approval.user?.name || `User ${approval.user_id}`}</span>
                                        <span className={`text-xs font-semibold uppercase ${approval.status === 'ready' || approval.status === 'approved' ? 'text-emerald-400' : 'text-[var(--color-text-muted)]'}`}>
                                            {approval.status}
                                        </span>
                                    </div>
                                ))}
                            </div>
                            <button
                                onClick={() => handleCompletion(isCurrentUserReady ? 'reopen' : 'mark_ready')}
                                disabled={updatingCompletion}
                                className="btn btn-success w-full"
                            >
                                {updatingCompletion
                                    ? 'Updating...'
                                    : isCurrentUserReady
                                        ? '↩️ Reopen Collaboration'
                                        : '✅ Mark Myself Ready'}
                            </button>
                        </div>
                    )}
                </div>

                <div className="lg:col-span-1">
                    <div className="glass-card-static p-5 sticky top-6">
                        <h3 className="text-white font-semibold mb-4 text-sm uppercase tracking-wider">
                            Activity Timeline
                        </h3>

                        <div className="space-y-0">
                            {workflow.events.length === 0 ? (
                                <p className="text-[var(--color-text-muted)] text-sm">No events yet.</p>
                            ) : (
                                [...workflow.events].reverse().map((event, idx) => (
                                    <div
                                        key={event.id}
                                        className="flex gap-3 py-3 border-b border-[var(--color-border)] last:border-0 animate-slide-in"
                                        style={{ animationDelay: `${idx * 30}ms` }}
                                    >
                                        <div className="text-base flex-shrink-0 mt-0.5">
                                            {eventIcons[event.event_type] || '📌'}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-[var(--color-text-secondary)] text-xs leading-relaxed">
                                                {event.message || event.event_type}
                                            </p>
                                            <div className="flex items-center gap-2 mt-1">
                                                <span className="text-[10px] text-[var(--color-text-muted)]">
                                                    {formatTime(event.created_at)}
                                                </span>
                                                {event.channel && (
                                                    <span className="text-[10px] text-purple-400 font-medium uppercase">
                                                        {event.channel}
                                                    </span>
                                                )}
                                                {event.actor && (
                                                    <span className="text-[10px] text-[var(--color-text-muted)]">
                                                        · {event.actor.name}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default WorkflowDetail;
