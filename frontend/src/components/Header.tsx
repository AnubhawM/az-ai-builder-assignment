// src/components/Header.tsx
import React from 'react';

interface User {
  id: number;
  name: string;
  role: string;
  email: string;
}

interface HeaderProps {
  currentUser: User | null;
  onSwitchPersona: () => void;
  onGoToMarketplace: () => void;
  onGoToDashboard: () => void;
  currentPage: string;
}

const roleLabels: Record<string, string> = {
  researcher: 'Researcher',
  compliance_expert: 'Compliance Expert',
  design_reviewer: 'Design Reviewer',
};

const Header: React.FC<HeaderProps> = ({ currentUser, onSwitchPersona, onGoToMarketplace, onGoToDashboard, currentPage }) => {
  return (
    <nav className="w-full border-b border-[var(--color-border)]"
      style={{ background: 'rgba(15, 22, 41, 0.95)' }}>
      <div className="w-full px-6 py-3">
        <div className="flex justify-between items-center max-w-7xl mx-auto">
          {/* Logo / Title */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white font-bold text-sm">
              AX
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight leading-none">
                AIXplore
              </h1>
              <p className="text-[10px] font-medium text-purple-400 tracking-widest uppercase leading-none mt-0.5">
                Capability Exchange
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={onGoToDashboard}
              className={`px-4 py-2 text-sm font-medium rounded-lg ${currentPage === 'dashboard' || currentPage === 'detail' ? 'text-white bg-white/10' : 'text-[var(--color-text-secondary)]'}`}
            >
              My Workflows
            </button>
            <button
              onClick={onGoToMarketplace}
              className={`px-4 py-2 text-sm font-medium rounded-lg ${currentPage === 'marketplace' || currentPage === 'marketplace-detail' ? 'text-white bg-white/10' : 'text-[var(--color-text-secondary)]'}`}
            >
              Marketplace
            </button>
          </div>

          {/* User Info */}
          {currentUser && (
            <div className="flex items-center gap-4">
              <div className="text-right hidden sm:block">
                <p className="text-sm font-medium text-white leading-none">
                  {currentUser.name}
                </p>
                <p className="text-xs text-purple-400 mt-0.5">
                  {roleLabels[currentUser.role] || currentUser.role}
                </p>
              </div>
              <button
                onClick={onSwitchPersona}
                className="btn btn-ghost text-xs px-3 py-1.5"
              >
                Switch Persona
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Header;
