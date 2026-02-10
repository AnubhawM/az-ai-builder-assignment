// src/components/PersonaSelector.tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';

interface User {
    id: number;
    name: string;
    email: string;
    role: string;
}

interface PersonaSelectorProps {
    onSelect: (user: User) => void;
}

const roleConfig: Record<string, { icon: string; description: string; color: string }> = {
    researcher: {
        icon: '🔬',
        description: 'Initiate research workflows, review findings, and generate presentations.',
        color: 'from-purple-500 to-indigo-600',
    },
    compliance_expert: {
        icon: '🛡️',
        description: 'Review research for compliance, regulatory alignment, and data accuracy.',
        color: 'from-blue-500 to-cyan-600',
    },
    design_reviewer: {
        icon: '🎨',
        description: 'Evaluate presentation design, layout, and visual communication quality.',
        color: 'from-emerald-500 to-teal-600',
    },
};

const roleLabels: Record<string, string> = {
    researcher: 'Researcher',
    compliance_expert: 'Compliance Expert',
    design_reviewer: 'Design Reviewer',
};

const PersonaSelector: React.FC<PersonaSelectorProps> = ({ onSelect }) => {
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [hoveredId, setHoveredId] = useState<number | null>(null);

    useEffect(() => {
        const fetchUsers = async () => {
            try {
                const res = await axios.get(`${import.meta.env.VITE_API_URL}/api/users`);
                setUsers(res.data.users);
            } catch (err) {
                console.error('Failed to fetch users:', err);
            } finally {
                setLoading(false);
            }
        };
        fetchUsers();
    }, []);

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                <div className="text-center">
                    <div className="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin-slow mx-auto mb-4" />
                    <p className="text-[var(--color-text-secondary)]">Loading personas...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen flex items-center justify-center px-6 py-12">
            <div className="max-w-3xl w-full animate-fade-in">
                {/* Header */}
                <div className="text-center mb-12">
                    <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white font-bold text-2xl mx-auto mb-6 shadow-lg shadow-purple-500/20">
                        AX
                    </div>
                    <h1 className="text-3xl font-bold text-white mb-3 tracking-tight">
                        AIXplore Capability Exchange
                    </h1>
                    <p className="text-[var(--color-text-secondary)] text-base max-w-md mx-auto">
                        Select your persona to access the collaborative research and presentation platform.
                    </p>
                </div>

                {/* Persona Cards */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    {users.map((user) => {
                        const config = roleConfig[user.role] || roleConfig.researcher;
                        const isHovered = hoveredId === user.id;

                        return (
                            <button
                                key={user.id}
                                onClick={() => onSelect(user)}
                                onMouseEnter={() => setHoveredId(user.id)}
                                onMouseLeave={() => setHoveredId(null)}
                                className="glass-card p-6 text-left cursor-pointer group"
                                style={{
                                    transform: isHovered ? 'translateY(-4px)' : 'translateY(0)',
                                    transition: 'all 0.3s ease',
                                }}
                                id={`persona-${user.role}`}
                            >
                                {/* Avatar */}
                                <div
                                    className={`w-12 h-12 rounded-xl bg-gradient-to-br ${config.color} flex items-center justify-center text-2xl mb-4 shadow-md transition-transform duration-300 ${isHovered ? 'scale-110' : ''}`}
                                >
                                    {config.icon}
                                </div>

                                {/* Name & Role */}
                                <h3 className="text-white font-semibold text-lg mb-1">
                                    {user.name}
                                </h3>
                                <p className="text-purple-400 text-xs font-medium uppercase tracking-wider mb-3">
                                    {roleLabels[user.role] || user.role}
                                </p>

                                {/* Description */}
                                <p className="text-[var(--color-text-secondary)] text-sm leading-relaxed">
                                    {config.description}
                                </p>

                                {/* Hover indicator */}
                                <div
                                    className={`mt-4 flex items-center gap-1 text-xs font-medium transition-all duration-300 ${isHovered ? 'text-purple-400 opacity-100' : 'text-transparent opacity-0'}`}
                                >
                                    Continue →
                                </div>
                            </button>
                        );
                    })}
                </div>

                {/* Footer note */}
                <p className="text-center text-[var(--color-text-muted)] text-xs mt-8">
                    Each persona provides a role-specific view of the workflow platform.
                </p>
            </div>
        </div>
    );
};

export default PersonaSelector;
