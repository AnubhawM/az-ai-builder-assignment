// src/App.tsx
import React, { useState } from 'react';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import Header from './components/Header';
import PersonaSelector from './components/PersonaSelector';
import WorkflowDashboard from './components/WorkflowDashboard';
import WorkflowDetail from './components/WorkflowDetail';

interface User {
  id: number;
  name: string;
  email: string;
  role: string;
}

type Page = 'persona' | 'dashboard' | 'detail';

const App: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [page, setPage] = useState<Page>('persona');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);

  const handleSelectPersona = (user: User) => {
    setCurrentUser(user);
    setPage('dashboard');
  };

  const handleSwitchPersona = () => {
    setCurrentUser(null);
    setPage('persona');
    setSelectedWorkflowId(null);
  };

  const handleSelectWorkflow = (workflowId: number) => {
    setSelectedWorkflowId(workflowId);
    setPage('detail');
  };

  const handleBackToDashboard = () => {
    setSelectedWorkflowId(null);
    setPage('dashboard');
  };

  return (
    <div className="w-full min-h-screen">
      {/* Show header on all pages except persona selector */}
      {page !== 'persona' && currentUser && (
        <Header currentUser={currentUser} onSwitchPersona={handleSwitchPersona} />
      )}

      {/* Page Router */}
      {page === 'persona' && (
        <PersonaSelector onSelect={handleSelectPersona} />
      )}

      {page === 'dashboard' && currentUser && (
        <WorkflowDashboard
          currentUser={currentUser}
          onSelectWorkflow={handleSelectWorkflow}
        />
      )}

      {page === 'detail' && currentUser && selectedWorkflowId && (
        <WorkflowDetail
          workflowId={selectedWorkflowId}
          currentUser={currentUser}
          onBack={handleBackToDashboard}
        />
      )}

      <ToastContainer
        position="bottom-right"
        autoClose={4000}
        theme="dark"
        toastStyle={{
          background: 'var(--color-surface-raised)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-primary)',
        }}
      />
    </div>
  );
};

export default App;
