// src/components/Marketplace.tsx
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
    user: { name: string; role: string; is_agent: boolean };
}

interface WorkRequest {
    id: number;
    title: string;
    description: string;
    required_capabilities: string[];
    status: string;
    requester_id: number;
    created_at: string;
    requester: { name: string; role: string };
    volunteers: Volunteer[];
}

interface MarketplaceProps {
    currentUser: User;
    onSelectRequest: (requestId: number) => void;
}

const CAPABILITY_OPTIONS = [
    'research',
    'presentation',
    'slides',
    'ppt_generation',
    'design',
    'branding',
    'compliance',
    'regulatory',
    'risk',
] as const;

const Marketplace: React.FC<MarketplaceProps> = ({ currentUser, onSelectRequest }) => {
    const [requests, setRequests] = useState<WorkRequest[]>([]);
    const [loading, setLoading] = useState(true);
    const [showPostForm, setShowPostForm] = useState(false);
    const [newTitle, setNewTitle] = useState('');
    const [newDesc, setNewDesc] = useState('');
    const [newCaps, setNewCaps] = useState<string[]>(['research']);
    const [posting, setPosting] = useState(false);

    const fetchRequests = useCallback(async () => {
        try {
            const res = await axios.get(`${import.meta.env.VITE_API_URL}/api/marketplace`);
            setRequests(res.data.requests);
        } catch (err) {
            console.error('Failed to fetch marketplace requests:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchRequests();
        const interval = setInterval(fetchRequests, 5000);
        return () => clearInterval(interval);
    }, [fetchRequests]);

    const handlePostRequest = async () => {
        if (!newTitle.trim() || !newDesc.trim() || posting) return;
        setPosting(true);
        try {
            await axios.post(`${import.meta.env.VITE_API_URL}/api/marketplace`, {
                title: newTitle.trim(),
                description: newDesc.trim(),
                requester_id: currentUser.id,
                required_capabilities: newCaps,
            });
            toast.success('Work request posted to marketplace!');
            setNewTitle('');
            setNewDesc('');
            setNewCaps(['research']);
            setShowPostForm(false);
            fetchRequests();
        } catch (err) {
            toast.error('Failed to post request');
            console.error(err);
        } finally {
            setPosting(false);
        }
    };

    const formatDate = (dateStr: string) => {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
    };

    const handleCapabilitySelection = (event: React.ChangeEvent<HTMLSelectElement>) => {
        const selected = Array.from(event.target.selectedOptions).map((option) => option.value);
        setNewCaps(selected);
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <div className="text-center">
                    <div className="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin-slow mx-auto mb-4" />
                    <p className="text-[var(--color-text-secondary)]">Loading marketplace...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto px-6 py-8">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h2 className="text-2xl font-bold text-white">Capability Marketplace</h2>
                    <p className="text-[var(--color-text-secondary)] text-sm mt-1">
                        Discover needs and volunteer your expertise
                    </p>
                </div>
                <button
                    onClick={() => setShowPostForm(!showPostForm)}
                    className="btn btn-primary"
                    id="post-request-btn"
                >
                    <span>+</span> Post a Need
                </button>
            </div>

            {/* Post Need Form */}
            {showPostForm && (
                <div className="glass-card p-6 mb-8">
                    <h3 className="text-white font-semibold mb-3">Post a New Work Request</h3>
                    <div className="space-y-4">
                        <div>
                            <label className="block text-xs font-medium text-[var(--color-text-muted)] uppercase mb-1">Title</label>
                            <input
                                type="text"
                                value={newTitle}
                                onChange={(e) => setNewTitle(e.target.value)}
                                placeholder="What do you need help with?"
                                className="w-full bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                            />
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-[var(--color-text-muted)] uppercase mb-1">Description</label>
                            <textarea
                                value={newDesc}
                                onChange={(e) => setNewDesc(e.target.value)}
                                placeholder="Describe the task and expectations..."
                                rows={3}
                                className="w-full bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                            />
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-[var(--color-text-muted)] uppercase mb-1">Required Capabilities</label>
                            <select
                                multiple
                                value={newCaps}
                                onChange={handleCapabilitySelection}
                                className="w-full bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-purple-500 min-h-[120px]"
                            >
                                {CAPABILITY_OPTIONS.map((capability) => (
                                    <option key={capability} value={capability}>
                                        {capability}
                                    </option>
                                ))}
                            </select>
                            <p className="text-[11px] text-[var(--color-text-muted)] mt-1">
                                Hold Cmd/Ctrl to select multiple capabilities.
                            </p>
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button onClick={() => setShowPostForm(false)} className="px-4 py-2 text-sm text-[var(--color-text-secondary)]">
                                Cancel
                            </button>
                            <button
                                onClick={handlePostRequest}
                                disabled={!newTitle.trim() || !newDesc.trim() || newCaps.length === 0 || posting}
                                className="btn btn-primary"
                            >
                                {posting ? 'Posting...' : 'Post to Board'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Requests List */}
            <div className="space-y-4">
                {requests.length === 0 ? (
                    <div className="glass-card-static p-12 text-center text-[var(--color-text-muted)]">
                        No open requests at the moment.
                    </div>
                ) : (
                    requests.map((r) => (
                        <div
                            key={r.id}
                            onClick={() => onSelectRequest(r.id)}
                            className="glass-card p-6 flex flex-col md:flex-row gap-6 cursor-pointer"
                        >
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-3 mb-2">
                                    <span className="text-xs font-semibold text-purple-400 uppercase tracking-widest bg-purple-500/10 px-2 py-0.5 rounded">
                                        Open Need
                                    </span>
                                    <span className="text-xs text-[var(--color-text-muted)]">•</span>
                                    <span className="text-xs text-[var(--color-text-muted)]">
                                        Posted by {r.requester.name}
                                    </span>
                                </div>
                                <h3 className="text-xl font-bold text-white mb-2">
                                    {r.title}
                                </h3>
                                <p className="text-[var(--color-text-secondary)] text-sm line-clamp-2 mb-4">
                                    {r.description}
                                </p>
                                <div className="flex flex-wrap gap-2">
                                    {r.required_capabilities.map((cap, idx) => (
                                        <span key={idx} className="bg-[var(--color-surface)] border border-[var(--color-border)] px-2 py-0.5 rounded text-[10px] text-[var(--color-text-secondary)] uppercase">
                                            {cap}
                                        </span>
                                    ))}
                                </div>
                            </div>

                            <div className="md:w-48 flex-shrink-0 flex flex-col justify-between border-t md:border-t-0 md:border-l border-[var(--color-border)] pt-4 md:pt-0 md:pl-6">
                                <div className="mb-4">
                                    <p className="text-xs text-[var(--color-text-muted)] uppercase mb-2">Volunteers</p>
                                    <div className="flex -space-x-2">
                                        {r.volunteers.length === 0 ? (
                                            <span className="text-xs text-[var(--color-text-muted)] italic">No one yet</span>
                                        ) : (
                                            r.volunteers.map((v) => (
                                                <div key={v.id} className="w-8 h-8 rounded-full bg-[var(--color-surface-raised)] border-2 border-[var(--color-bg)] flex items-center justify-center text-[10px] text-white font-bold" title={v.user.name}>
                                                    {v.user.name.charAt(0)}
                                                </div>
                                            ))
                                        )}
                                    </div>
                                    {r.volunteers.length > 0 && (
                                        <p className="text-[10px] text-emerald-400 mt-2 font-medium">
                                            {r.volunteers.length} volunteer{r.volunteers.length !== 1 ? 's' : ''}
                                            {r.volunteers.some(v => v.user.is_agent) && ' (incl. AI)'}
                                        </p>
                                    )}
                                </div>
                                <div className="text-right">
                                    <p className="text-[10px] text-[var(--color-text-muted)]">{formatDate(r.created_at)}</p>
                                    <span className="text-purple-400 text-sm font-medium inline-flex items-center gap-1 mt-1">
                                        View & Volunteer <span>→</span>
                                    </span>
                                </div>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default Marketplace;
