// src/layouts/MainLayout.tsx
import React from 'react';

const MainLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  return (
    <div className="w-full min-h-screen">
      <main className="w-full">
        {children}
      </main>
    </div>
  );
};

export default MainLayout;
