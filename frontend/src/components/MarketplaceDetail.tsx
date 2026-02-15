// src/components/MarketplaceDetail.tsx
import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { toast } from 'react-toastify';

interface User {
    id: number;
    name: string;
    role: string;
    email: string;
}

interface Volunteer {
    id: number;
    user_id: number;
    note: string;
    status: string;
    created_at: string;
    user: { name: string; role: string; is_agent: boolean; email: string };
}

interface WorkRequest {
    id: number;
    title: string;
    description: string;
    required_capabilities: string[];
    status: string;
    requester_id: number;
    parent_workflow_id?: number | null;
    created_at: string;
    requester: { name: string; role: string };
    volunteers: Volunteer[];
}

interface MarketplaceDetailProps {
    requestId: number;
    currentUser: User;
    onBack: () => void;
    onStartWorkflow: (workflowId: number) => void;
}

const MarketplaceDetail: React.FC<MarketplaceDetailProps> = ({ requestId, currentUser, onBack, onStartWorkflow }) => {
    const [request, setRequest] = useState<WorkRequest | null>(null);
    const [loading, setLoading] = useState(true);
    const [volunteering, setVolunteering] = useState(false);
    const [volunteerNote, setVolunteerNote] = useState('');
    const [accepting, setAccepting] = useState<number | null>(null);

    const fetchDetail = useCallback(async () => {
        try {
            const res = await axios.get(`${import.meta.env.VITE_API_URL}/api/marketplace/${requestId}`);
            setRequest(res.data.request);
        } catch (err) {
            console.error('Failed to fetch request detail:', err);
            toast.error('Failed to load request');
            onBack();
        } finally {
            setLoading(false);
        }
    }, [requestId, onBack]);

    useEffect(() => {
        fetchDetail();
        const interval = setInterval(fetchDetail, 5000);
        return () => clearInterval(interval);
    }, [fetchDetail]);

    const handleVolunteer = async () => {
        if (volunteering) return;
        setVolunteering(true);
        try {
            await axios.post(`${import.meta.env.VITE_API_URL}/api/marketplace/${requestId}/volunteer`, {
                user_id: currentUser.id,
                note: volunteerNote.trim()
            });
            toast.success('You have volunteered for this task!');
            setVolunteerNote('');
            fetchDetail();
        } catch (err) {
            toast.error('Failed to volunteer');
        } finally {
            setVolunteering(false);
        }
    };

    const handleAccept = async (volunteerId: number) => {
        if (accepting !== null) return;
        setAccepting(volunteerId);
        try {
            const res = await axios.post(`${import.meta.env.VITE_API_URL}/api/marketplace/${requestId}/accept`, {
                volunteer_id: volunteerId,
                user_id: currentUser.id
            });
            toast.success('Handshake complete! Work has begun.');
            onStartWorkflow(res.data.workflow_id);
        } catch (err) {
            toast.error('Failed to accept volunteer');
        } finally {
            setAccepting(null);
        }
    };

    if (loading) return <div className="py-20 text-center text-white">Loading details...</div>;
    if (!request) return null;

    const isRequester = currentUser.id === request.requester_id;
    const isDirectInvite = (note: string) => (note || '').startsWith('Direct invite');
    const myInvite = request.volunteers.find(
        (v) => v.user_id === currentUser.id && v.status === 'pending' && isDirectInvite(v.note)
    );
    const hasVolunteered = request.volunteers.some(
        (v) => v.user_id === currentUser.id && !isDirectInvite(v.note)
    );

    return (
        <div className="max-w-4xl mx-auto px-6 py-8">
            <button onClick={onBack} className="text-[var(--color-text-secondary)] mb-6 flex items-center gap-2">
                ← Back to Marketplace
            </button>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                <div className="md:col-span-2 space-y-8">
                    {/* Header & Description */}
                    <div className="glass-card-static p-8">
                        <div className="flex items-center gap-3 mb-4">
                            <span className="bg-purple-500/10 text-purple-400 border border-purple-500/20 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider">
                                Discovery Phase
                            </span>
                        </div>
                        <h1 className="text-3xl font-bold text-white mb-4">{request.title}</h1>
                        <div className="flex items-center gap-4 text-sm text-[var(--color-text-secondary)] mb-6 border-b border-[var(--color-border)] pb-6">
                            <div className="flex items-center gap-2">
                                <div className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center text-[10px] text-white">
                                    {request.requester.name.charAt(0)}
                                </div>
                                <span>{request.requester.name}</span>
                            </div>
                            <span>•</span>
                            <span>{new Date(request.created_at).toLocaleDateString()}</span>
                        </div>

                        <div className="prose prose-invert max-w-none">
                            <h4 className="text-white text-sm uppercase tracking-widest mb-2 font-semibold">Description</h4>
                            <p className="text-[var(--color-text-secondary)] leading-relaxed">
                                {request.description}
                            </p>
                        </div>

                        <div className="mt-8">
                            <h4 className="text-white text-sm uppercase tracking-widest mb-3 font-semibold">Required Capabilities</h4>
                            <div className="flex flex-wrap gap-2">
                                {request.required_capabilities.map((cap, i) => (
                                    <span key={i} className="bg-[var(--color-surface)] border border-[var(--color-border)] px-3 py-1 rounded text-xs text-purple-300">
                                        {cap}
                                    </span>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Volunteers List */}
                    <div>
                        <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-3">
                            Volunteers ({request.volunteers.length})
                        </h3>
                        <div className="space-y-4">
                            {request.volunteers.length === 0 ? (
                                <div className="glass-card-static p-8 text-center text-[var(--color-text-muted)] italic">
                                    Awaiting volunteers...
                                </div>
                            ) : (
                                request.volunteers.map((v) => (
                                    <div key={v.id} className={`glass-card p-6 flex items-start gap-4 ${v.status === 'accepted' ? 'border-emerald-500/50' : ''}`}>
                                        <div className={`w-12 h-12 rounded-full flex-shrink-0 flex items-center justify-center text-lg font-bold text-white ${v.user.is_agent ? 'bg-emerald-600 shadow-[0_0_15px_rgba(16,185,129,0.3)]' : 'bg-purple-600'}`}>
                                            {v.user.is_agent ? '🤖' : v.user.name.charAt(0)}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center justify-between mb-1">
                                                <h4 className="text-white font-bold inline-flex items-center gap-2">
                                                    {v.user.name}
                                                    {v.user.is_agent && <span className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded border border-emerald-500/20">AGENT</span>}
                                                </h4>
                                                <span className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider">
                                                    {new Date(v.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                                </span>
                                            </div>
                                            <p className="text-xs text-purple-400 mb-2 uppercase tracking-tight">{v.user.role.replace('_', ' ')}</p>
                                            <p className="text-[var(--color-text-secondary)] text-sm italic bg-[var(--color-bg)]/50 p-3 rounded-lg border border-[var(--color-border)]/50">
                                                "{v.note || 'I am ready to help with this project!'}"
                                            </p>
                                        </div>
                                        {isRequester && request.status === 'open' && (
                                            <button
                                                onClick={() => handleAccept(v.id)}
                                                disabled={accepting !== null}
                                                className="btn btn-primary px-6 py-2 h-auto text-sm"
                                            >
                                                {accepting === v.id ? 'Connecting...' : 'Accept & Start'}
                                            </button>
                                        )}
                                        {v.status === 'accepted' && (
                                            <div className="text-emerald-400 font-bold text-sm bg-emerald-500/10 px-4 py-2 rounded-lg border border-emerald-500/20">
                                                ACCEPTED
                                            </div>
                                        )}
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                </div>

                {/* Sidebar Actions */}
                <div className="space-y-6">
                    {!isRequester && request.status === 'open' && !!myInvite && (
                        <div className="glass-card p-6 border-emerald-500/30">
                            <h4 className="text-white font-bold mb-3 uppercase text-xs tracking-widest">Direct Invite</h4>
                            <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                                You were invited by the requester to collaborate on this need.
                            </p>
                            <button
                                onClick={() => handleAccept(myInvite.id)}
                                disabled={accepting !== null}
                                className="btn btn-primary w-full"
                            >
                                {accepting === myInvite.id ? 'Starting...' : 'Accept & Start'}
                            </button>
                        </div>
                    )}

                    {!isRequester && request.status === 'open' && !hasVolunteered && !myInvite && (
                        <div className="glass-card p-6 border-purple-500/30">
                            <h4 className="text-white font-bold mb-3 uppercase text-xs tracking-widest">Your Proposal</h4>
                            <textarea
                                value={volunteerNote}
                                onChange={(e) => setVolunteerNote(e.target.value)}
                                placeholder="Briefly state why you are a good match..."
                                rows={4}
                                className="w-full bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500 mb-4"
                            />
                            <button
                                onClick={handleVolunteer}
                                disabled={volunteering}
                                className="btn btn-primary w-full"
                            >
                                {volunteering ? 'Sending...' : 'Volunteer Now'}
                            </button>
                            <p className="text-[var(--color-text-muted)] text-[10px] mt-3 text-center">
                                The requester will review all volunteers and choose a partner for this task.
                            </p>
                        </div>
                    )}

                    {hasVolunteered && request.status === 'open' && (
                        <div className="glass-card p-6 border-emerald-500/30 text-center">
                            <div className="text-2xl mb-2">✅</div>
                            <h4 className="text-emerald-400 font-bold mb-1">Volunteered</h4>
                            <p className="text-[var(--color-text-muted)] text-xs">
                                Awaiting the requester's decision.
                            </p>
                        </div>
                    )}

                    <div className="glass-card-static p-6">
                        <h4 className="text-white font-bold mb-4 uppercase text-xs tracking-widest">Marketplace Info</h4>
                        <div className="space-y-4">
                            <div>
                                <p className="text-[10px] text-[var(--color-text-muted)] uppercase">Status</p>
                                <p className="text-sm font-medium text-white capitalize">{request.status}</p>
                            </div>
                            <div>
                                <p className="text-[10px] text-[var(--color-text-muted)] uppercase">Matches</p>
                                <p className="text-sm font-medium text-white">{request.volunteers.length} volunteer(s)</p>
                            </div>
                            <div>
                                <p className="text-[10px] text-[var(--color-text-muted)] uppercase">Type</p>
                                <p className="text-sm font-medium text-white">{request.parent_workflow_id ? 'Recursive Sub-task' : 'Primary Workflow'}</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MarketplaceDetail;
