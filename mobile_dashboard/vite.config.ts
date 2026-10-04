import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('.',import.meta.url));
export default defineConfig({root,plugins:[react()],resolve:{alias:{'@':root}},define:{'process.env.NODE_ENV':JSON.stringify('production')},build:{target:'es2020',outDir:'../assets/dashboard',emptyOutDir:true,cssCodeSplit:false,lib:{entry:root+'mobile-entry.tsx',name:'PhilthySportsDashboard',formats:['iife'],fileName:()=> 'dashboard.js',cssFileName:'dashboard'},rollupOptions:{output:{inlineDynamicImports:true}}}});
