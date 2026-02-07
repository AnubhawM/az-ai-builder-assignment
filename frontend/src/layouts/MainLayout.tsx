// src/layouts/MainLayout.tsx
import React from 'react';
import Header from '../components/Header';

const MainLayout: React.FC<{children: React.ReactNode}> = ({children}) => {
  return (
    <div className="w-full min-h-screen bg-gray-100">
      <Header />
      <main className="w-full">
        <div className="w-full">
          {children}
        </div>
      </main>
    </div>
  );
};


export default MainLayout;
