import { createRoot } from 'react-dom/client';
import './widget.css';
import { createBridge } from './bridge';
import { Widget } from './Widget';

const bridge = createBridge();
createRoot(document.getElementById('root')!).render(<Widget bridge={bridge} />);
