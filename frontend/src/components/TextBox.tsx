import React from 'react';

interface TextBoxProps {
  response: string;
}

const TextBox: React.FC<TextBoxProps> = ({ response }) => {
  return (
    <div className="mt-6 w-full max-w-lg p-4 bg-white border border-gray-300 rounded-lg shadow-md">
      <h2 className="text-xl font-semibold mb-2">Generated Response:</h2>
      <p>{response}</p>
    </div>
  );
};

export default TextBox;
