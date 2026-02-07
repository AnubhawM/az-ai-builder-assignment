// src/components/Header.tsx
import React, { useEffect } from 'react';  // Add useEffect import
import { useAuth0 } from '@auth0/auth0-react';

const Header: React.FC = () => {
  const { isAuthenticated, user, loginWithRedirect, logout, getAccessTokenSilently } = useAuth0();  // Add getAccessTokenSilently

  useEffect(() => {
    const registerUser = async () => {
      if (isAuthenticated && user) {
        try {
          const token = await getAccessTokenSilently();
          const response = await fetch('http://localhost:5000/register', {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${token}`,
              'Content-Type': 'application/json'
            }
          });
          const data = await response.json();
          console.log('User registration:', data);
        } catch (error) {
          console.error('Registration error:', error);
        }
      }
    };

    registerUser();
  }, [isAuthenticated, user, getAccessTokenSilently]);

  return (
    <nav className="w-full bg-blue-500">
      <div className="w-full px-6 py-4">
        <div className="flex justify-between items-center max-w-7xl mx-auto">
          <h1 className="text-2xl font-bold text-white">TEMPLATE</h1>
          <div className="flex items-center gap-4">

            {isAuthenticated ? (
              <>
                <span className="text-white hidden sm:inline">Welcome, {user?.name}</span>
                <button
                  onClick={() => logout({ 
                    logoutParams: { returnTo: window.location.origin }
                  })}
                  className="bg-white px-6 py-2 rounded-md text-blue-500 hover:bg-blue-50"
                >
                  Log Out
                </button>
              </>
            ) : (
              <button
                onClick={() => loginWithRedirect()}
                className="bg-white px-6 py-2 rounded-md text-blue-500 hover:bg-blue-50"
              >
                Log In
              </button>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
};

export default Header;
