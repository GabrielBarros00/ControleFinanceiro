/** @jsxImportSource preact */
import { render } from 'preact';
import './widget.css';
import { createBridge } from './bridge';
import { Widget } from './Widget';

const bridge = createBridge();
render(<Widget bridge={bridge} />, document.getElementById('root')!);
